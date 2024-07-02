# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from typing import List

from kubernetes import client, config

# Load kubeconfig
from kubernetes.client import ApiException, V1Deployment

config.load_kube_config()


def create_secret(api_instance, namespace, secret_name, data):
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name=secret_name),
        string_data=data
    )
    api_instance.create_namespaced_secret(namespace, secret)


def create_deployment(api_instance, namespace, app_name, image, replicas, resources, env_vars, secret_name=None):
    env = [client.V1EnvVar(name=var['Key'], value=var['Value']) for var in env_vars if not var.get('IsSecret')]
    if secret_name:
        for var in env_vars:
            if var.get('IsSecret'):
                env.append(client.V1EnvVar(
                    name=var['Key'],
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=secret_name,
                            key=var['Key']
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


def create_service(api_instance, namespace, app_name, service_port):
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=app_name),
        spec=client.V1ServiceSpec(
            selector={"app": app_name},
            ports=[client.V1ServicePort(port=service_port, target_port=service_port)]
        )
    )
    api_instance.create_namespaced_service(namespace, service)


def create_ingress(api_instance, namespace, app_name, domain):
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


def add_new_application(app_data):
    namespace = 'default'  # Change as needed
    api_instance = client.CoreV1Api()
    apps_api = client.AppsV1Api()
    networking_v1_api = client.NetworkingV1Api()

    app_name = app_data['AppName']
    replicas = app_data['Replicas']
    image = f"{app_data['ImageAddress']}:{app_data['ImageTag']}"
    service_port = app_data['ServicePort']
    resources = {
        'cpu': app_data['Resources']['CPU'],
        'memory': app_data['Resources']['RAM']
    }
    env_vars = app_data['Envs']
    domain = app_data.get('DomainAddress')

    secret_name = None
    if any(env.get('IsSecret') for env in env_vars):
        secret_name = f"{app_name}-secret"
        secret_data = {env['Key']: env['Value'] for env in env_vars if env.get('IsSecret')}
        create_secret(api_instance, namespace, secret_name, secret_data)

    create_deployment(apps_api, namespace, app_name, image, replicas, resources, env_vars, secret_name)
    create_service(api_instance, namespace, app_name, service_port)

    if domain:
        create_ingress(networking_v1_api, namespace, app_name, domain)


def deployment_status(deployment:V1Deployment, core_api, namespace):
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


def get_deployment_status(namespace, app_name):
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()

    deployments = []
    if len(app_name) >= 1:
        try:
            return deployment_status(apps_api.read_namespaced_deployment(name=app_name, namespace=namespace), core_api, namespace)
        except ApiException as e:
            if e.status == 404:
                return {"error": f"Deployment {app_name} not found in namespace {namespace}"}
            else:
                return {"error": str(e)}
    else:
        deployments = apps_api.list_namespaced_deployment(namespace=namespace)
        all_deployment_status = []
        for deployment in deployments.items:
            all_deployment_status.append(deployment_status(deployment,core_api, namespace))

    print(all_deployment_status)
    return all_deployment_status


app_data = {
    "AppName": "myapp2",
    "Replicas": 3,
    "ImageAddress": "dockerhub.com/hello-world",
    "ImageTag": "latest",
    "DomainAddress": "myapp.example.com",
    "ServicePort": 8080,
    "Resources": {
        "CPU": "500m",
        "RAM": "1Gi"
    },
    "Envs": [
        {
            "Key": "DATABASE_URL",
            "Value": "postgres://user:password@db.example.com:5432/mydb",
            "IsSecret": True
        },
        {
            "Key": "REDIS_HOST",
            "Value": "redis.example.com",
            "IsSecret": False
        },
        {
            "Key": "API_KEY",
            "Value": "myapikey",
            "IsSecret": False
        }
    ]
}

# add_new_application(app_data)
get_deployment_status('default', app_name='')
