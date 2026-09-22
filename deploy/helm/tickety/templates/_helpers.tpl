{{- define "tickety.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "tickety.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "tickety.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "tickety.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "tickety.labels" -}}
helm.sh/chart: {{ include "tickety.chart" . }}
app.kubernetes.io/name: {{ include "tickety.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "tickety.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tickety.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "tickety.componentLabels" -}}
{{ include "tickety.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "tickety.secretName" -}}
{{- default (printf "%s-secrets" (include "tickety.fullname" .)) .Values.existingSecret }}
{{- end }}

{{- define "tickety.configName" -}}
{{- printf "%s-config" (include "tickety.fullname" .) }}
{{- end }}

{{- define "tickety.postgresqlName" -}}
{{- printf "%s-postgresql" (include "tickety.fullname" .) }}
{{- end }}

{{- define "tickety.frontendUrl" -}}
{{- if .Values.config.frontendUrl -}}
{{- .Values.config.frontendUrl -}}
{{- else if .Values.ingress.enabled -}}
{{- $scheme := ternary "https" "http" (gt (len .Values.ingress.tls) 0) -}}
{{- printf "%s://%s" $scheme .Values.ingress.host -}}
{{- else -}}
http://localhost:3000
{{- end -}}
{{- end }}

{{- define "tickety.backendImage" -}}
{{- include "tickety.applicationImage" (dict "root" . "image" .Values.backend.image "component" "backend") }}
{{- end }}

{{- define "tickety.applicationImage" -}}
{{- $root := .root -}}
{{- $image := .image -}}
{{- $component := .component -}}
{{- $digest := $image.digest | default "" -}}
{{- if $digest -}}
  {{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
    {{- fail (printf "%s.image.digest must be a sha256 manifest digest" $component) -}}
  {{- end -}}
  {{- printf "%s@%s" $image.repository $digest -}}
{{- else -}}
  {{- if ($root.Values.imageDigestPolicy.requireDigests | default false) -}}
    {{- fail (printf "%s.image.digest is required when imageDigestPolicy.requireDigests=true" $component) -}}
  {{- end -}}
  {{- printf "%s:%s" $image.repository ($image.tag | default $root.Chart.AppVersion) -}}
{{- end -}}
{{- end }}

{{- define "tickety.workerImage" -}}
{{- $backendTag := .Values.backend.image.tag | default .Chart.AppVersion -}}
{{- if and .Values.worker.image.repository (ne .Values.worker.image.repository .Values.backend.image.repository) -}}
{{- fail "worker.image.repository must match backend.image.repository; worker and migration code must share one release image" -}}
{{- end -}}
{{- if and .Values.worker.image.tag (ne .Values.worker.image.tag $backendTag) -}}
  {{- fail "worker.image.tag must match backend.image.tag; worker and migration code must share one release image" -}}
{{- end -}}
{{- if and .Values.worker.image.digest (ne .Values.worker.image.digest .Values.backend.image.digest) -}}
  {{- fail "worker.image.digest must match backend.image.digest; worker and migration code must share one release image" -}}
{{- end -}}
{{- include "tickety.backendImage" . }}
{{- end }}

{{- define "tickety.frontendImage" -}}
{{- include "tickety.applicationImage" (dict "root" . "image" .Values.frontend.image "component" "frontend") }}
{{- end }}

{{- define "tickety.postgresqlImage" -}}
{{- $image := .Values.postgresql.image -}}
{{- $digest := $image.digest | default "" -}}
{{- if $digest -}}
  {{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
    {{- fail "postgresql.image.digest must be a sha256 manifest digest" -}}
  {{- end -}}
  {{- printf "%s@%s" $image.repository $digest -}}
{{- else -}}
  {{- if (.Values.imageDigestPolicy.requireDigests | default false) -}}
    {{- fail "postgresql.image.digest is required when imageDigestPolicy.requireDigests=true and bundled PostgreSQL is enabled" -}}
  {{- end -}}
  {{- printf "%s:%s" $image.repository $image.tag -}}
{{- end -}}
{{- end }}

{{- define "tickety.existingSecretRolloutAnnotations" -}}
{{- if .Values.existingSecret -}}
tickety.io/existing-secret-rollout-token: {{ .Values.existingSecretRolloutToken | quote }}
{{- end -}}
{{- end }}

{{- define "tickety.workerPullPolicy" -}}
{{- .Values.worker.image.pullPolicy | default .Values.backend.image.pullPolicy -}}
{{- end }}

{{- define "tickety.waitForDatabase" -}}
- name: wait-for-database
  image: {{ include "tickety.backendImage" . | quote }}
  imagePullPolicy: {{ .Values.backend.image.pullPolicy }}
  command:
    - python
    - -c
    - |
      import os, time
      import psycopg2
      url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
      for attempt in range(90):
          try:
              connection = psycopg2.connect(url, connect_timeout=3)
              connection.close()
              print("Database is ready")
              break
          except Exception:
              if attempt == 89:
                  raise
              time.sleep(2)
  envFrom:
    - secretRef:
        name: {{ include "tickety.secretName" . }}
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      cpu: 250m
      memory: 256Mi
  securityContext:
    runAsUser: 10001
    runAsGroup: 10001
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
  volumeMounts:
    - name: tmp
      mountPath: /tmp
{{- end }}

{{- define "tickety.waitForSchema" -}}
- name: wait-for-migrations
  image: {{ include "tickety.backendImage" . | quote }}
  imagePullPolicy: {{ .Values.backend.image.pullPolicy }}
  command:
    - python
    - -c
    - |
      import time
      from app.backend.database import verify_database_schema
      for attempt in range(150):
          try:
              verify_database_schema()
              print("Database migrations are complete")
              break
          except Exception:
              if attempt == 149:
                  raise
              time.sleep(2)
  envFrom:
    - configMapRef:
        name: {{ include "tickety.configName" . }}
    - secretRef:
        name: {{ include "tickety.secretName" . }}
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      cpu: 250m
      memory: 256Mi
  securityContext:
    runAsUser: 10001
    runAsGroup: 10001
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
  volumeMounts:
    - name: tmp
      mountPath: /tmp
{{- end }}
