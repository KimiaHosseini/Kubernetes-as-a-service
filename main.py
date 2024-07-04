import logging
import psycopg2
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, generate_latest, Gauge
import time
from pydantic import BaseModel
from typing import List, Optional

from kubernetes import client, config
from kubernetes.client import ApiException, V1Deployment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config.load_incluster_config()
logger.info("load incluster config passed")

app = FastAPI()


class EnvVar(BaseModel):
    Key: str
    Value: str
    IsSecret: bool


class AppData(BaseModel):
    AppName: str
    Monitor: str
    Replicas: Optional[int] = 1
    ImageAddress: str
    ImageTag: str
    DomainAddress: Optional[str] = None
    ServicePort: int
    Resources: dict
    Envs: List[EnvVar]


class PostgresAppData(BaseModel):
    AppName: str
    Resources: dict
    External: Optional[bool] = False


# Prometheus metrics
REQUEST_COUNT = Counter("num_requests", "Total number of requests", ['path'])
FAILED_REQUEST_COUNT = Counter("num_failed_requests", "Total number of failed requests", ['path'])
RESPONSE_TIME = Gauge("response_time", "Response time in seconds", ['path'])
DB_ERROR_COUNT = Counter("num_db_errors", "Total number of database errors", ['path'])
DB_RESPONSE_TIME = Gauge("db_response_time", "Database response time in seconds", ['path'])


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    REQUEST_COUNT.labels(path=request.url.path).inc()
    start_time = time.perf_counter()

    response = await call_next(request)

    process_time = (time.perf_counter() - start_time) * 1000
    RESPONSE_TIME.labels(path=request.url.path).set(process_time)

    if response.status_code >= 400:
        FAILED_REQUEST_COUNT.labels(path=request.url.path).inc()

    return response


@app.get("/metrics")
def get_metrics():
    return Response(generate_latest(), media_type="text/plain")


def _create_secret(api_instance, namespace, secret_name, data):
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name=secret_name),
        string_data=data
    )
    api_instance.create_namespaced_secret(namespace, secret)


def _create_deployment(api_instance, namespace, app_name, image, replicas, resources, env_vars, secret_name=None):
    env = [client.V1EnvVar(name=var.Key, value=var.Value) for var in env_vars if not var.IsSecret]
    if secret_name:
        for var in env_vars:
            if var.IsSecret:
                env.append(client.V1EnvVar(
                    name=var.Key,
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=secret_name,
                            key=var.Key
                        )
                    )
                ))

    container = client.V1Container(
        name=app_name,
        image=image,
        env=env,
        resources=client.V1ResourceRequirements(
            requests=resources
        )
    )
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": app_name}),
        spec=client.V1PodSpec(containers=[container])
    )
    spec = client.V1DeploymentSpec(
        replicas=replicas,
        template=template,
        selector={'matchLabels': {'app': app_name}}
    )
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=app_name),
        spec=spec
    )
    api_instance.create_namespaced_deployment(
        namespace=namespace,
        body=deployment
    )


def _create_service(api_instance, namespace, app_name, service_port):
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=app_name),
        spec=client.V1ServiceSpec(
            selector={"app": app_name},
            ports=[client.V1ServicePort(port=service_port, target_port=service_port)]
        )
    )
    api_instance.create_namespaced_service(namespace, service)


def _create_ingress(api_instance, namespace, app_name, domain):
    ingress = client.V1Ingress(
        metadata=client.V1ObjectMeta(name=app_name),
        spec=client.V1IngressSpec(
            rules=[client.V1IngressRule(
                host=domain,
                http=client.V1HTTPIngressRuleValue(
                    paths=[client.V1HTTPIngressPath(
                        path="/",
                        path_type="ImplementationSpecific",
                        backend=client.V1IngressBackend(
                            service=client.V1IngressServiceBackend(
                                name=app_name,
                                port=client.V1ServiceBackendPort(number=80)
                            )
                        )
                    )]
                )
            )]
        )
    )
    api_instance.create_namespaced_ingress(namespace, ingress)


def _create_cronjob(api_instance, namespace, app_name, port, db_config):
    cronjob = client.V1CronJob(
        metadata=client.V1ObjectMeta(name=f"{app_name}-health-check"),
        spec=client.V1CronJobSpec(
            schedule="*/5 * * * *",
            job_template=client.V1JobTemplateSpec(
                spec=client.V1JobSpec(
                    template=client.V1PodTemplateSpec(
                        spec=client.V1PodSpec(
                            containers=[client.V1Container(
                                name="health-check-container",
                                image="postgres:latest",
                                env=[
                                    client.V1EnvVar(name="DB_HOST", value=db_config['DB_HOST']),
                                    client.V1EnvVar(name="DB_PORT", value=db_config['DB_PORT']),
                                    client.V1EnvVar(name="DB_NAME", value=db_config['DB_NAME']),
                                    client.V1EnvVar(name="DB_USER", value=db_config['DB_USER']),
                                    client.V1EnvVar(name="DB_PASSWORD", value=db_config['DB_PASSWORD'])
                                ],
                                args=[
                                    "/bin/bash", "-c", f'''
                                    apt-get update && apt-get install -y curl
                                    status=$(curl -s -o /dev/null -w "%{{http_code}}" http://{app_name}.{namespace}.svc.cluster.local:{port}/healthz)
                                    timestamp=$(date +%s)
                                    if [ "$status" -eq 200 ]; then
                                        psql postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME -c "INSERT INTO health_status (app_name, failure_count, success_count, last_failure, last_success, created_at) VALUES ('{app_name}', 0, 1, NULL, to_timestamp($timestamp), to_timestamp($timestamp)) ON CONFLICT (app_name) DO UPDATE SET success_count = health_status.success_count + 1, last_success = to_timestamp($timestamp);"
                                    else
                                        psql postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME -c "INSERT INTO health_status (app_name, failure_count, success_count, last_failure, last_success, created_at) VALUES ('{app_name}', 1, 0, to_timestamp($timestamp), NULL, to_timestamp($timestamp)) ON CONFLICT (app_name) DO UPDATE SET failure_count = health_status.failure_count + 1, last_failure = to_timestamp($timestamp);"
                                    fi
                                    '''
                                ]
                            )],
                            restart_policy="OnFailure"
                        )
                    )
                )
            )
        )
    )
    api_instance.create_namespaced_cron_job(namespace, cronjob)


def _get_db_config(namespace):
    api_instance = client.CoreV1Api()
    configmap = api_instance.read_namespaced_config_map(name="db-config", namespace=namespace)
    db_config = {
        "DB_HOST": configmap.data["DB_HOST"],
        "DB_PORT": configmap.data["DB_PORT"],
        "DB_NAME": configmap.data["DB_NAME"],
        "DB_USER": configmap.data["DB_USER"],
        "DB_PASSWORD": configmap.data["DB_PASSWORD"],
        "DB_HOST_SLAVE": configmap.data["DB_HOST_SLAVE"]
    }
    return db_config


def api_add_new_application(app_data: AppData):
    namespace = 'default'
    api_instance = client.CoreV1Api()
    apps_api = client.AppsV1Api()
    networking_v1_api = client.NetworkingV1Api()
    batch_api = client.BatchV1Api()

    app_name = app_data.AppName
    replicas = app_data.Replicas
    image = f"{app_data.ImageAddress}:{app_data.ImageTag}"
    service_port = app_data.ServicePort
    resources = {
        'cpu': app_data.Resources['CPU'],
        'memory': app_data.Resources['RAM']
    }
    env_vars = app_data.Envs
    domain = app_data.DomainAddress
    monitor = app_data.Monitor

    secret_name = None
    if any(env.IsSecret for env in env_vars):
        secret_name = f"{app_name}-secret"
        secret_data = {env.Key: env.Value for env in env_vars if env.IsSecret}
        _create_secret(api_instance, namespace, secret_name, secret_data)

    _create_deployment(apps_api, namespace, app_name, image, replicas, resources, env_vars, secret_name)
    _create_service(api_instance, namespace, app_name, service_port)

    if domain:
        _create_ingress(networking_v1_api, namespace, app_name, domain)

    create_health_status_table()

    if monitor == "true":
        db_config = _get_db_config(namespace)
        _create_cronjob(batch_api, namespace, app_name, service_port, db_config)


def _deployment_status(deployment: V1Deployment, core_api, namespace):
    status = {
        "DeploymentName": deployment.metadata.name,
        "Replicas": deployment.spec.replicas,
        "ReadyReplicas": deployment.status.ready_replicas,
        "PodStatuses": []
    }
    pod_list = core_api.list_namespaced_pod(namespace, label_selector=f"app={deployment.metadata.name}")
    for pod in pod_list.items:
        pod_status = {
            "Name": pod.metadata.name,
            "Phase": pod.status.phase,
            "HostIP": pod.status.host_ip,
            "PodIP": pod.status.pod_ip,
            "StartTime": pod.status.start_time.strftime("%m/%d/%Y, %H:%M:%S")
        }
        status["PodStatuses"].append(pod_status)
    return status


def api_get_deployment_status(namespace, app_name):
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()

    if app_name:
        try:
            return _deployment_status(apps_api.read_namespaced_deployment(name=app_name, namespace=namespace),
                                      core_api, namespace)
        except ApiException as e:
            if e.status == 404:
                return {"error": f"Deployment {app_name} not found in namespace {namespace}"}
            else:
                return {"error": str(e)}
    else:
        deployments = apps_api.list_namespaced_deployment(namespace=namespace)
        all_deployment_status = []
        for deployment in deployments.items:
            all_deployment_status.append(_deployment_status(deployment, core_api, namespace))

    return all_deployment_status


def _create_configmap(api_instance, namespace, configmap_name, config_data):
    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=configmap_name),
        data=config_data
    )
    api_instance.create_namespaced_config_map(namespace, configmap)


def _create_statefulset(api_instance, namespace, app_name, image, resources, configmap_name, secret_name, external):
    env = [
        client.V1EnvVar(
            name="POSTGRES_USER",
            value_from=client.V1EnvVarSource(
                secret_key_ref=client.V1SecretKeySelector(
                    name=secret_name,
                    key="POSTGRES_USER"
                )
            )
        ),
        client.V1EnvVar(
            name="POSTGRES_PASSWORD",
            value_from=client.V1EnvVarSource(
                secret_key_ref=client.V1SecretKeySelector(
                    name=secret_name,
                    key="POSTGRES_PASSWORD"
                )
            )
        ),
    ]

    volume_mounts = [
        client.V1VolumeMount(
            name="postgres-config",
            mount_path="/etc/postgresql"
        )
    ]

    volumes = [
        client.V1Volume(
            name="postgres-config",
            config_map=client.V1ConfigMapVolumeSource(
                name=configmap_name
            )
        )
    ]

    container = client.V1Container(
        name=app_name,
        image=image,
        resources=client.V1ResourceRequirements(
            requests=resources
        ),
        env=env,
        volume_mounts=volume_mounts
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": app_name}),
        spec=client.V1PodSpec(containers=[container], volumes=volumes)
    )

    spec = client.V1StatefulSetSpec(
        service_name=app_name,
        replicas=1,
        selector={'matchLabels': {'app': app_name}},
        template=template,
        volume_claim_templates=[]
    )

    statefulset = client.V1StatefulSet(
        api_version="apps/v1",
        kind="StatefulSet",
        metadata=client.V1ObjectMeta(name=app_name),
        spec=spec
    )

    api_instance.create_namespaced_stateful_set(namespace, statefulset)


def api_create_postgres_service(app_data: PostgresAppData):
    namespace = 'default'
    api_instance = client.CoreV1Api()
    apps_api = client.AppsV1Api()
    networking_v1_api = client.NetworkingV1Api()

    app_name = app_data.AppName
    resources = {
        'cpu': app_data.Resources['cpu'],
        'memory': app_data.Resources['memory']
    }
    image = "postgres:latest"
    secret_name = f"{app_name}-secret"
    configmap_name = f"{app_name}-config"

    secret_data = {
        "POSTGRES_USER": "admin",
        "POSTGRES_PASSWORD": "adminpass"
    }
    _create_secret(api_instance, namespace, secret_name, secret_data)

    config_data = {
        "postgresql.conf": "shared_buffers = 128MB\nmax_connections = 100"
    }
    _create_configmap(api_instance, namespace, configmap_name, config_data)

    _create_statefulset(apps_api, namespace, app_name, image, resources, configmap_name, secret_name, app_data.External)

    _create_service(api_instance, namespace, app_name, 5432)

    if app_data.External:
        _create_ingress(networking_v1_api, namespace, app_name, f"{app_name}.example.com")


def api_health(app_name: str):
    namespace = 'default'
    db_config = _get_db_config(namespace)

    connection = None
    try:
        # Connect to the PostgreSQL database
        connection = psycopg2.connect(
            host=db_config['DB_HOST_SLAVE'],
            port=db_config['DB_PORT'],
            database=db_config['DB_NAME'],
            user=db_config['DB_USER'],
            password=db_config['DB_PASSWORD']
        )

        cursor = connection.cursor()
        # Query the health_status table for the specified app_name
        cursor.execute("SELECT * FROM health_status WHERE app_name = %s", (app_name,))
        result = cursor.fetchone()

        if result:
            return {
                "app_name": result[0],
                "failure_count": result[1],
                "success_count": result[2],
                "last_failure": result[3],
                "last_success": result[4],
                "created_at": result[5]
            }
        else:
            return {"status": "No health status found for the application"}

    except Exception as e:
        return {"status": "unhealthy", "details": str(e)}

    finally:
        if connection:
            connection.close()


def create_health_status_table():
    namespace = 'default'
    db_config = _get_db_config(namespace)

    connection = None
    try:
        connection = psycopg2.connect(
            host=db_config['DB_HOST'],
            port=db_config['DB_PORT'],
            database=db_config['DB_NAME'],
            user=db_config['DB_USER'],
            password=db_config['DB_PASSWORD']
        )

        cursor = connection.cursor()

        # SQL to create the health_status table
        create_table_query = '''
        CREATE TABLE IF NOT EXISTS health_status (
            app_name VARCHAR(255) PRIMARY KEY,
            failure_count INT NOT NULL,
            success_count INT NOT NULL,
            last_failure TIMESTAMP,
            last_success TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        '''
        cursor.execute(create_table_query)
        connection.commit()

    except Exception as e:
        print(f"Error creating table: {e}")

    finally:
        if connection:
            connection.close()

@app.post("/applications")
def add_new_application(app_data: AppData):
    try:
        api_add_new_application(app_data)
        return {"status": "Application created successfully"}
    except Exception as e:
        FAILED_REQUEST_COUNT.labels(path='/applications').inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/deployments/{namespace}/{app_name}")
@app.get("/deployments/{namespace}")
def get_deployment_status(namespace: str, app_name: Optional[str] = ''):
    try:
        return api_get_deployment_status(namespace, app_name)
    except Exception as e:
        FAILED_REQUEST_COUNT.labels(path='/deployments').inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/postgres")
def create_postgres_service(app_data: PostgresAppData):
    try:
        api_create_postgres_service(app_data)
        return {"status": "Postgres service created successfully"}
    except Exception as e:
        logger.info("self-service: failed because" + str(e))
        FAILED_REQUEST_COUNT.labels(path='/postgres').inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ping")
def ping():
    try:
        return {"status": "pong"}
    except Exception as e:
        FAILED_REQUEST_COUNT.labels(path='/ping').inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health/{app_name}")
def health(app_name: str):
    try:
        return api_health(app_name)
    except Exception as e:
        FAILED_REQUEST_COUNT.labels(path='/health/').inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/healthz")
def liveness():
    try:
        logger.info("liveness: done")
        return {"status": "ok"}
    except Exception as e:
        logger.error("liveness: failed because" + str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ready")
def readiness():
    namespace = "default"
    app_name = "kaas-api"
    try:
        apps_api = client.AppsV1Api()
        deployment = apps_api.read_namespaced_deployment(name=app_name, namespace=namespace)
        logger.info("readiness: deployment status created in readiness")
        # Check if the deployment has at least one ready replica
        if deployment.spec.replicas is None or deployment.spec.replicas < 1:
            logger.error("readiness: there is no replica created")
            raise HTTPException(status_code=500, detail="Application is not ready yet")
        logger.info("readiness: done")
        return {"status": "ok"}
    except Exception as e:
        logger.info(str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/startup")
def startup():
    try:
        api_instance = client.CoreV1Api()
        api_instance.get_api_resources()
        logger.info("startup: done")
        return {"status": "ok"}
    except Exception as e:
        logger.info("startup: failed because" + str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
