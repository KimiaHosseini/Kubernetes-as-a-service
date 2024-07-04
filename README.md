# Kubernetes as a Service (KaaS)

Welcome to Kubernetes as a Service (KaaS)! You will find in this repo all the needed configurations and code to deploy and manage applications on Kubernetes, from setting up a PostgreSQL database with master-slave replication, an API service, to monitoring with Prometheus and Grafana.
## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Monitoring](#monitoring)

## Overview
The goal of KaaS is to simplify the processes around deployment and management of applications on Kubernetes. We provide an API service based on FastAPI, which is responsible for interacting with the Kubernetes API to manage the life cycle of Deployments, Services, and monitoring configurations.

## Features
- **FastAPI** for creating and managing Kubernetes resources
- **self-service postgreSQL app** for creating a complete postgres environment with the least input data
- **PostgreSQL** with master-slave replication
- **Horizontal Pod Autoscaler (HPA)**
- **Ingress** for routing external traffic
- **Prometheus** and **Grafana** for monitoring and alerting
- **Automated health checks** using Kubernetes CronJobs

## Prerequisites
- Kubernetes cluster (minikube, GKE, EKS, etc.)
- kubectl configured to interact with your Kubernetes cluster
- Helm installed and configured
- Python 3.7+ for running the FastAPI application

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/KimiaHosseini/Kubernetes-as-a-service.git
   cd Kubernetes-as-a-service
   ```

3. Install Kaas-api with helm:
   ```bash
   helm package kaas-api
   helm install kaas-api ./kaas-api-0.1.0.tgz
   ```
   
## Usage

Ater running kaas-api pod:
   ```bash
   kubectl port-forward <kaas-api-pod-name> 8000
   ```

The API provides the following endpoints:
- `POST /applications`: Create a new application deployment.
- `GET /deployments/{namespace}/{app_name}`: Get the status of a deployment.
- `GET /deployments/{namespace}`: Get the status of all deployments.
- `POST /postgres`: Create a self--service PostgreSQL service.
- `GET /health/{app_name}`: Get health status of an application.
- `GET /healthz`: Check liveness of the API service.
- `GET /ready`: Check readiness of the API service.
- `GET /startup`: Check startup status of the API service.

### Example
Create a new application deployment:
```bash
curl -X POST "http://localhost:8000/applications" -H "Content-Type: application/json" -d '{
    "AppName": "my-app",
    "Monitor": "true",
    "Replicas": 2,
    "ImageAddress": "my-docker-repo/my-app",
    "ImageTag": "latest",
    "ServicePort": 8080,
    "Resources": {
        "CPU": "500m",
        "RAM": "512Mi"
    },
    "Envs": [
        {"Key": "ENV_VAR", "Value": "value", "IsSecret": false}
    ]
}'
```

## Monitoring
Install and configure Prometheus and Grafana for monitoring:

Install Prometheus
   ```bash
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm repo update
   helm install prometheus prometheus-community/prometheus
   kubectl port-forward <prometheus-pod-name> 9090
   ```

Install grafana
   ```bash
   helm repo add grafana https://grafana.github.io/helm-charts
   helm repo update
   helm install grafana grafana/grafana
   kubectl port-forward <grafana-pod-name> 3000
   ```

Now you can see prometheus and grafan UI in localhost:9090 and localhost:3000.

```bash
kubectl get secret --namespace default grafana -o jsonpath="{.data.admin-password}" | base64 --decode
```

Use the above command to get the Grafana admin password and login.

For grafana datasource, use the prometheus datasource with this url : http://prometheus-server.default.svc.cluster.local:80
For grafana dashboard you can use ./kaas-api/grafana/dashboard.yaml or make it your own with specified metrics in main.py.

---

For more detailed information, refer to the attached report `report.pdf`.

Feel free to reach out if you have any questions or need further assistance.
