# MoFaaS Controller Repository

This repository contains the implementation and evaluation of the MoFaaS (Multi-variant Function as a Service) as described in our paper. The repository is organized into two branches:

- **main**: Contains the functional blocks of the MoFaaS Controller.
- **evaluation**: Includes tests and results obtained during the evaluation phase.

## Components

- **egress-proxy**: Corresponds to the Outbound Controller in the paper.
- **function-chooser**: Implements the Trigger Controller.
- **mofaas-controller**: The Kubernetes MoFaaS Controller.
- **init-iptables**: Container that modifies iptables rules at startup.
- **modified-envoy**: Envoy sidecar with custom configurations.

## Prerequisites

Before launching the MoFaaS Controller, ensure you have the following installed:

1. **Kyverno**:
    - Install Kyverno following the [official documentation](https://kyverno.io/docs/installation/methods/).
    - After installing, upgrade it like so to enable policy exceptions:
        ```sh
        helm upgrade kyverno kyverno/kyverno -n kyverno --set features.policyExceptions.enabled=true --set features.policyExceptions.namespace="*"
        ```

2. **Knative**:
   - Install Knative [Serving](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/) and [Eventing](https://knative.dev/docs/install/yaml-install/eventing/install-eventing-with-yaml/) following the official documentation.
        - Ensure the Kafka Channel and Broker are set up.

## Setup

1. **Apply Kyverno Cluster Policy**:
   ```sh
   kubectl apply -f kyverno.yaml
   ```

2. **Deploy MoFaaS Kubernetes Controller**:
   ```sh
   cd mofaas-controller
   make deploy
   ```

## Testing Applications

The repository includes two applications used for testing:

### 1. Bank Application

A simple bank app that allows for making transactions. It requires Directus and MySQL.

#### Launch Database and Directus:
```sh
cd mysql-baas
kubectl apply -f mysql.yaml
kubectl apply -f directus.yaml
```

#### Launch the Bank App:
```sh
cd apps/bank/
# Apply patches for Knative controllers to access MoFaaS custom resources
./patch

# Deploy the app
cd chart/
helm install bank .
```

**Note**: The bank app includes vulnerable functions in multiple languages (Java, JS, Go, PHP, Python). The Python version is vulnerable, while others are not. You can modify the `values.yaml` file in the Helm chart to change settings like concurrent versions per function or function variants.

### 2. Sample Workflow

This app launches multiple interconnected functions with the same implementation to study the performance impact of MoFaaS.

#### Launch the Sample Workflow:
```sh
cd apps/sample-workflow/chart
helm install sample-workflow .
```

You can modify the `values.yaml` file to change the size of the workflow and the number of variants for each function.

## MoFaaS LLM Feedback Loop

The MoFaaS LLM Feedback Loop was implemented and is available in another repository: https://github.com/ATNoG/mofaas-version-generation. Please refer to it if you want to try it and contribute.

## Contributing

We welcome contributions! Please open an issue or submit a pull request.

## License

This project is licensed under the GPL-3.0 License. See the [LICENSE](LICENSE) file for details.