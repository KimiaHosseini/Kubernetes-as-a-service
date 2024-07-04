# Kubernetes as a Service (KaaS) README

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
   helm install kaas-chart .
   ```

## Usage
Start the FastAPI application using uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API provides the following endpoints:
- `POST /applications`: Create a new application deployment.
- `GET /deployments/{namespace}/{app_name}`: Get the status of a deployment.
- `POST /postgres`: Create a PostgreSQL service.
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
```bash
kubectl apply -f prometheus.yaml
kubectl apply -f grafana.yaml
kubectl port-forward svc/prometheus 9090:9090
kubectl port-forward svc/grafana 3000:3000
```

Access Grafana at `http://localhost:3000` and configure the data source to point to Prometheus:
```bash
kubectl get secret --namespace default grafana -o jsonpath="{.data.admin-password}" | base64 --decode
```

Use the above command to get the Grafana admin password and login.

---

For more detailed information, refer to the attached report `cc final.pdf`.

Feel free to reach out if you have any questions or need further assistance.

---

This README provides an overview and setup guide for the KaaS project, enabling users to deploy and manage Kubernetes applications effectively.
