{{/*
Expand the name of the chart.
*/}}
{{- define "kaas-api.name" -}}
{{- default .Chart.Name (index .Values "nameOverride" | default "") | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "kaas-api.fullname" -}}
"kaas-api"
{{- end -}}
{{/*
Common labels
*/}}
{{- define "kaas-api.labels" -}}
app.kubernetes.io/name: {{ include "kaas-api.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "kaas-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kaas-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
