# knative-mofaas

## To create the skeleton for the Controller
```bash
$ go mod init mofaas
$ kubebuilder init
$ kubebuilder create api --group mofaas --domain atnog --version v1 --kind MoFaaSFunction
$ go get knative.dev/serving/pkg/apis/serving/v1

# For webhooks
$ kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.1/cert-manager.yaml
$ kubebuilder create webhook --group mofaas --version v1 --kind MoFaaSFunction --programmatic-validation

# To install
$ make install
$ make deploy

# To uninstall
$ make undeploy
$ make uninstall
```


## Requirements
### Install Kyverno

```bash
$ helm repo add kyverno https://kyverno.github.io/kyverno/
$ helm repo update
$ helm install kyverno kyverno/kyverno -n kyverno --create-namespace
```
#### TODO -> It is required to allow the PolicyException in kyverno

helm upgrade kyverno kyverno/kyverno -n kyverno --set features.policyExceptions.enabled=true --set features.policyExceptions.namespace="*"


