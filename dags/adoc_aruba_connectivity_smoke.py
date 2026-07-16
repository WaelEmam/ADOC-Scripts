from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from airflow.exceptions import AirflowException
from airflow.hooks.base import BaseHook
from airflow import DAG as AirflowDAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

try:
    from acceldata_airflow_sdk.dag import DAG as AcceldataDAG
    from acceldata_airflow_sdk.operators.torch_initialiser_operator import TorchInitializer
    from acceldata_sdk.models.pipeline import PipelineMetadata

    ACCELDATA_SDK_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:
    AcceldataDAG = None
    TorchInitializer = None
    PipelineMetadata = None
    ACCELDATA_SDK_IMPORT_ERROR = exc


LOGGER = logging.getLogger(__name__)
TORCH_INITIALIZER_TASK_ID = "torch_pipeline_initializer"
CONNECTION_ID_XCOM_KEY = "CONNECTION_ID"


def setting(name: str, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value

    try:
        return Variable.get(name, default_var=default)
    except Exception:
        LOGGER.debug("Could not read Airflow Variable %s; using default", name, exc_info=True)
        return default


DAG_ID = setting("ADOC_AIRFLOW_SMOKE_DAG_ID", "adoc_aruba_connectivity_smoke")
CONNECTION_ID = setting("ADOC_AIRFLOW_CONNECTION_ID", "aruba_acceldata_connection")
PIPELINE_UID = setting("ADOC_AIRFLOW_PIPELINE_UID", "adoc.airflow.aruba.connectivity_smoke")
PIPELINE_NAME = setting("ADOC_AIRFLOW_PIPELINE_NAME", "ADOC Aruba Airflow Connectivity Smoke")
PIPELINE_OWNER = setting("ADOC_AIRFLOW_PIPELINE_OWNER", "Wael Emam")
PIPELINE_TEAM = setting("ADOC_AIRFLOW_PIPELINE_TEAM", "SE Team")
CODE_LOCATION = setting(
    "ADOC_AIRFLOW_CODE_LOCATION",
    "ADOC-Scripts/dags/adoc_aruba_connectivity_smoke.py",
)
SMOKE_PATHS = setting(
    "ADOC_AIRFLOW_SMOKE_PATHS",
    "/catalog-server/api/rules?page=0&size=1&withLatestExecution=false,"
    "/api/catalog-server/api/rules?page=0&size=1&withLatestExecution=false",
)


default_args = {
    "owner": PIPELINE_OWNER,
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


dag_class = AcceldataDAG or AirflowDAG


def dag_id_from_context(context) -> str:
    dag = context.get("dag")
    if dag is not None:
        return dag.dag_id

    dag_run = context.get("dag_run")
    if dag_run is not None:
        return dag_run.dag_id

    return DAG_ID


def initializer_xcom(context, key: str):
    task_instance = context.get("ti") or context.get("task_instance")
    if task_instance is None:
        return None
    return task_instance.xcom_pull(task_ids=TORCH_INITIALIZER_TASK_ID, key=key)


def update_adoc_pipeline_run(context, *, success: bool, raise_on_error: bool) -> None:
    try:
        from acceldata_airflow_sdk.initialiser import torch_credentials
        from acceldata_sdk.events.generic_event import GenericEvent
        from acceldata_sdk.models.pipeline import PipelineRunResult, PipelineRunStatus
        from acceldata_sdk.torch_client import TorchClient

        dag_id = dag_id_from_context(context)
        pipeline_run_id = initializer_xcom(context, f"{dag_id}_pipeline_run_id")
        connection_id = initializer_xcom(context, CONNECTION_ID_XCOM_KEY) or CONNECTION_ID

        if not pipeline_run_id:
            message = (
                f"Could not find ADOC pipeline run id in XCom from "
                f"{TORCH_INITIALIZER_TASK_ID!r}"
            )
            if raise_on_error:
                raise AirflowException(message)
            LOGGER.warning(message)
            return

        LOGGER.info(
            "Finalizing ADOC pipeline run id=%s connection_id=%s success=%s",
            pipeline_run_id,
            connection_id,
            success,
        )

        client = TorchClient(**torch_credentials(connection_id))
        pipeline_run = client.get_pipeline_run(pipeline_run_id=pipeline_run_id)
        root_span = pipeline_run.get_root_span()

        if success:
            root_span.end(context_data={"dag_status": "SUCCESS", "time": str(datetime.now())})
            pipeline_run.update_pipeline_run(
                context_data={"status": "success", "dag": dag_id},
                result=PipelineRunResult.SUCCESS,
                status=PipelineRunStatus.COMPLETED,
            )
        else:
            root_span.send_event(
                GenericEvent(
                    context_data={"dag_status": "FAILED", "time": str(datetime.now())},
                    event_uid=f"{root_span.span.uid}.error.event",
                )
            )
            root_span.failed(context_data={"dag_status": "FAILED", "time": str(datetime.now())})
            pipeline_run.update_pipeline_run(
                context_data={"status": "failure", "dag": dag_id},
                result=PipelineRunResult.FAILURE,
                status=PipelineRunStatus.FAILED,
            )
    except Exception:
        LOGGER.exception("Failed to finalize ADOC pipeline run")
        if raise_on_error:
            raise


def finalize_adoc_pipeline_success(**context) -> None:
    update_adoc_pipeline_run(context, success=True, raise_on_error=True)


def finalize_adoc_pipeline_failure(context) -> None:
    update_adoc_pipeline_run(context, success=False, raise_on_error=False)


dag_kwargs = {
    "dag_id": DAG_ID,
    "default_args": default_args,
    "description": "End-to-end Acceldata ADOC connectivity smoke test for the Aruba tenant.",
    "schedule": None,
    "start_date": datetime(2026, 7, 14),
    "catchup": False,
    "tags": ["adoc", "aruba", "connectivity", "smoke-test"],
    "on_failure_callback": finalize_adoc_pipeline_failure,
}

if AcceldataDAG:
    dag_kwargs.update(
        {
            "override_success_callback": True,
            "override_failure_callback": True,
        }
    )


dag = dag_class(**dag_kwargs)


def raise_missing_acceldata_sdk() -> None:
    raise AirflowException(
        "Missing Acceldata Airflow SDK dependency. Install both packages in the "
        "Airflow scheduler and worker environment: "
        "pip install acceldata-sdk acceldata-airflow-sdk. "
        f"Original import error: {ACCELDATA_SDK_IMPORT_ERROR}"
    )


def validate_airflow_connection() -> None:
    try:
        connection = BaseHook.get_connection(CONNECTION_ID)
    except Exception as exc:
        raise AirflowException(
            f"Airflow connection {CONNECTION_ID!r} is not available inside the task "
            "runtime. Create it in Airflow Admin > Connections, or add it to the "
            "same metadata database/secrets backend used by your Docker task "
            "containers, before triggering this DAG."
        ) from exc

    missing_fields = []
    if not connection.host:
        missing_fields.append("Host")
    if not connection.login:
        missing_fields.append("Login")
    if not connection.password:
        missing_fields.append("Password")
    if missing_fields:
        raise AirflowException(
            f"Airflow connection {CONNECTION_ID!r} is missing required field(s): "
            f"{', '.join(missing_fields)}"
        )


connection_preflight_task = PythonOperator(
    task_id="validate_airflow_connection",
    python_callable=validate_airflow_connection,
    dag=dag,
)


if TorchInitializer and PipelineMetadata:
    torch_initializer_task = TorchInitializer(
        task_id=TORCH_INITIALIZER_TASK_ID,
        pipeline_uid=PIPELINE_UID,
        pipeline_name=PIPELINE_NAME,
        connection_id=CONNECTION_ID,
        meta=PipelineMetadata(
            owner=PIPELINE_OWNER,
            team=PIPELINE_TEAM,
            codeLocation=CODE_LOCATION,
        ),
        dag=dag,
    )
else:
    torch_initializer_task = PythonOperator(
        task_id="install_acceldata_airflow_sdk",
        python_callable=raise_missing_acceldata_sdk,
        dag=dag,
    )


def connection_base_url(connection) -> str:
    host = (connection.host or "").strip().rstrip("/")
    if not host:
        raise AirflowException(f"Airflow connection {CONNECTION_ID!r} does not have a host")

    if "://" not in host:
        scheme = connection.schema or "https"
        host = f"{scheme}://{host}"

    parsed = urlsplit(host)
    if connection.port and ":" not in parsed.netloc:
        parsed = parsed._replace(netloc=f"{parsed.netloc}:{connection.port}")

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def connection_headers(connection) -> dict[str, str]:
    extra = connection.extra_dejson or {}
    access_key_header = extra.get("access_key_header", "accessKey")
    secret_key_header = extra.get("secret_key_header", "secretKey")

    if not connection.login or not connection.password:
        raise AirflowException(
            f"Airflow connection {CONNECTION_ID!r} must include the ADOC access key "
            "as Login and secret key as Password"
        )

    headers = {
        "Accept": "application/json",
        access_key_header: connection.login,
        secret_key_header: connection.password,
    }

    tenant_id = (
        extra.get("ADOC_TENANT_ID")
        or extra.get("X_TENANT_ID")
        or extra.get("TENANT_ID")
        or extra.get("tenant_id")
    )
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id

    return headers


def configured_timeout_seconds(connection) -> float:
    extra = connection.extra_dejson or {}
    raw_timeout = extra.get("TORCH_READ_TIMEOUT_MS") or extra.get("read_timeout_ms") or 15000
    try:
        return max(float(raw_timeout) / 1000, 1.0)
    except (TypeError, ValueError):
        return 15.0


def candidate_paths() -> list[str]:
    paths = [path.strip() for path in SMOKE_PATHS.split(",") if path.strip()]
    if not paths:
        raise AirflowException("ADOC_AIRFLOW_SMOKE_PATHS did not contain any paths")
    return paths


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: "***"
        if any(part in key.lower() for part in ("key", "secret", "password", "authorization"))
        else value
        for key, value in headers.items()
    }


def validate_adoc_http_connection(**context) -> dict[str, object]:
    connection = BaseHook.get_connection(CONNECTION_ID)
    base_url = connection_base_url(connection)
    headers = connection_headers(connection)
    timeout = configured_timeout_seconds(connection)

    LOGGER.info(
        "Running ADOC connectivity smoke test with connection_id=%s base_url=%s headers=%s",
        CONNECTION_ID,
        base_url,
        redact_headers(headers),
    )

    last_error: Exception | None = None
    for path in candidate_paths():
        url = f"{base_url}/{path.lstrip('/')}"
        request = Request(url, headers=headers, method="GET")

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(4096)
                result = {
                    "url": url,
                    "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "sampled_bytes": len(payload),
                }
                LOGGER.info("ADOC connectivity smoke test succeeded: %s", json.dumps(result))
                return result
        except HTTPError as exc:
            body = exc.read(1000).decode("utf-8", errors="replace")
            last_error = AirflowException(f"GET {url} failed with HTTP {exc.code}: {body}")
            if exc.code not in {404, 405}:
                break
        except URLError as exc:
            last_error = AirflowException(f"GET {url} failed: {exc.reason}")
            break

    raise last_error or AirflowException("ADOC connectivity smoke test failed")


http_connectivity_task = PythonOperator(
    task_id="validate_adoc_http_connection",
    python_callable=validate_adoc_http_connection,
    dag=dag,
)


finalize_adoc_pipeline_task = PythonOperator(
    task_id="finalize_adoc_pipeline_success",
    python_callable=finalize_adoc_pipeline_success,
    dag=dag,
)


connection_preflight_task >> torch_initializer_task >> http_connectivity_task >> finalize_adoc_pipeline_task
