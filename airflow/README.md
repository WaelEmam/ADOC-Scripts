# Airflow ADOC Connectivity Smoke DAG

An end-to-end Airflow DAG that validates ADOC connectivity from inside an Airflow
environment, at:

```bash
adoc_aruba_connectivity_smoke.py
```

Copy or sync this file into your Airflow `dags/` folder. The DAG expects the
`acceldata-sdk` and `acceldata-airflow-sdk` packages to be installed in the Airflow
environment.

## Table Of Contents

- [Installing The SDK Packages](#installing-the-sdk-packages)
- [Connection Setup](#connection-setup)
- [DAG Tasks](#dag-tasks)
- [Configuration Overrides](#configuration-overrides)

## Installing The SDK Packages

For Docker-based Airflow, install the packages in the Airflow containers used by the
scheduler, webserver, and worker. If you only have `docker-compose.yml` and no
Dockerfile, add `_PIP_ADDITIONAL_REQUIREMENTS` to the shared Airflow environment block.

Many Airflow Compose files have an `x-airflow-common` section. Add the requirement there:

```yaml
x-airflow-common:
  &airflow-common
  environment:
    &airflow-common-env
    _PIP_ADDITIONAL_REQUIREMENTS: "acceldata-sdk acceldata-airflow-sdk"
```

If your file already has `_PIP_ADDITIONAL_REQUIREMENTS`, append the two packages to the
existing value. Then recreate Airflow:

```bash
docker compose up -d
```

Verify the imports in the scheduler container:

```bash
docker compose exec airflow-scheduler python -c "import acceldata_airflow_sdk, acceldata_sdk; print('ok')"
```

If you run CeleryExecutor, verify the worker container too:

```bash
docker compose exec airflow-worker python -c "import acceldata_airflow_sdk, acceldata_sdk; print('ok')"
```

For a quick non-persistent test, you can install inside running containers instead, but
this will be lost when containers are recreated:

```bash
docker compose exec airflow-scheduler pip install acceldata-sdk acceldata-airflow-sdk
docker compose exec airflow-worker pip install acceldata-sdk acceldata-airflow-sdk
docker compose exec airflow-webserver pip install acceldata-sdk acceldata-airflow-sdk
```

## Connection Setup

By default, the DAG uses an Airflow HTTP connection named:

```text
aruba_acceldata_connection
```

Configure that connection with:

- `Host`: Aruba ADOC tenant URL, for example `https://<tenant-host>`
- `Login`: ADOC access key
- `Password`: ADOC secret key
- `Extra`: optional JSON such as:

```json
{
  "ADOC_TENANT_ID": "<tenant-id>",
  "ENABLE_VERSION_CHECK": false,
  "TORCH_CONNECTION_TIMEOUT_MS": 10000,
  "TORCH_READ_TIMEOUT_MS": 20000
}
```

## DAG Tasks

The DAG has four tasks:

```text
validate_airflow_connection
torch_pipeline_initializer
validate_adoc_http_connection
finalize_adoc_pipeline_success
```

`validate_airflow_connection` checks that the `aruba_acceldata_connection` connection is
visible inside the Airflow task runtime before ADOC creates a pipeline run.
`TorchInitializer` starts the ADOC pipeline run, the direct HTTP smoke-test task validates
tenant connectivity, and `finalize_adoc_pipeline_success` explicitly ends the ADOC root
span and marks the pipeline run `COMPLETED`. The DAG also has a failure callback that
attempts to mark the ADOC pipeline run `FAILED` if a task fails after initialization.

The smoke task intentionally does not use the SDK `@job` decorator because the decorator
can fall back to `torch.acceldata.local` unless the SDK environment variables are also
configured in every Airflow container.

If you later add `@job`-decorated tasks, set these environment variables in Docker
Compose as well:

```text
TORCH_CATALOG_URL
TORCH_ACCESS_KEY
TORCH_SECRET_KEY
```

## Configuration Overrides

You can override these DAG values with Airflow Variables or environment variables:

```text
ADOC_AIRFLOW_CONNECTION_ID
ADOC_AIRFLOW_PIPELINE_UID
ADOC_AIRFLOW_PIPELINE_NAME
ADOC_AIRFLOW_PIPELINE_OWNER
ADOC_AIRFLOW_PIPELINE_TEAM
ADOC_AIRFLOW_CODE_LOCATION
ADOC_AIRFLOW_SMOKE_PATHS
```

`ADOC_AIRFLOW_SMOKE_PATHS` is a comma-separated list of GET paths to try. The default
tries both the direct and `/api`-prefixed catalog rules endpoint.
