{{/*
Expand the name of the chart.
*/}}
{{- define "fastapi-chassis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "fastapi-chassis.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Allow the release namespace to be overridden (Bitnami pattern #9).
*/}}
{{- define "fastapi-chassis.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "fastapi-chassis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "fastapi-chassis.labels" -}}
helm.sh/chart: {{ include "fastapi-chassis.chart" . }}
{{ include "fastapi-chassis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "fastapi-chassis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fastapi-chassis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "fastapi-chassis.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "fastapi-chassis.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the internal application port (what uvicorn listens on).
*/}}
{{- define "fastapi-chassis.containerPort" -}}
{{- .Values.app.port | default 8000 }}
{{- end }}

{{/*
Return true if the SQLite backend is selected
*/}}
{{- define "fastapi-chassis.isSqlite" -}}
{{- eq (.Values.database.backend | default "postgres") "sqlite" }}
{{- end }}

{{/*
Return true if LiteFS is active (sqlite + litefs.enabled)
*/}}
{{- define "fastapi-chassis.isLitefs" -}}
{{- and (eq (.Values.database.backend | default "postgres") "sqlite") .Values.litefs.enabled }}
{{- end }}

{{/*
Return the port exposed by the container — LiteFS proxy port when active,
otherwise the app port directly.
*/}}
{{- define "fastapi-chassis.exposedPort" -}}
{{- if eq (include "fastapi-chassis.isLitefs" .) "true" -}}
{{- .Values.litefs.proxy.port | default 8080 }}
{{- else -}}
{{- include "fastapi-chassis.containerPort" . }}
{{- end -}}
{{- end }}

{{/*
Return the workload kind based on database backend.
SQLite requires a StatefulSet for stable storage identity.
*/}}
{{- define "fastapi-chassis.workloadKind" -}}
{{- if eq (include "fastapi-chassis.isSqlite" .) "true" -}}
StatefulSet
{{- else -}}
Deployment
{{- end -}}
{{- end }}

{{/*
Headless service name for StatefulSet.
*/}}
{{- define "fastapi-chassis.headlessServiceName" -}}
{{- printf "%s-headless" (include "fastapi-chassis.fullname" .) }}
{{- end }}

{{/* =======================================================================
   Bitnami-inspired helpers
   ======================================================================= */}}

{{/*
Return the proper container image name (Bitnami pattern #1).
Supports global registry override, per-image registry, digest pinning,
and falls back to the chart appVersion for the tag.

Usage:
  {{ include "fastapi-chassis.image" (dict "imageRoot" .Values.image "global" (.Values.global | default dict) "defaultTag" .Chart.AppVersion) }}
*/}}
{{- define "fastapi-chassis.image" -}}
{{- $registry := .imageRoot.registry | default "" -}}
{{- if .global -}}
  {{- if .global.imageRegistry -}}
    {{- $registry = .global.imageRegistry -}}
  {{- end -}}
{{- end -}}
{{- $repository := .imageRoot.repository -}}
{{- $digest := .imageRoot.digest | default "" -}}
{{- if $digest -}}
  {{- if $registry -}}
    {{- printf "%s/%s@%s" $registry $repository $digest -}}
  {{- else -}}
    {{- printf "%s@%s" $repository $digest -}}
  {{- end -}}
{{- else -}}
  {{- $tag := .imageRoot.tag | default .defaultTag | default "latest" -}}
  {{- if $registry -}}
    {{- printf "%s/%s:%s" $registry $repository ($tag | toString) -}}
  {{- else -}}
    {{- printf "%s:%s" $repository ($tag | toString) -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Return the proper imagePullSecrets, merging global and local values (Bitnami pattern #4).
Supports both map format ({name: secret}) and string format (just the name).

Usage:
  {{- include "fastapi-chassis.imagePullSecrets" . | nindent 6 }}
*/}}
{{- define "fastapi-chassis.imagePullSecrets" -}}
{{- $pullSecrets := list -}}
{{- if .Values.global -}}
  {{- range .Values.global.imagePullSecrets -}}
    {{- if kindIs "map" . -}}
      {{- $pullSecrets = append $pullSecrets . -}}
    {{- else -}}
      {{- $pullSecrets = append $pullSecrets (dict "name" .) -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- range .Values.imagePullSecrets -}}
  {{- if kindIs "map" . -}}
    {{- $pullSecrets = append $pullSecrets . -}}
  {{- else -}}
    {{- $pullSecrets = append $pullSecrets (dict "name" .) -}}
  {{- end -}}
{{- end -}}
{{- if $pullSecrets }}
imagePullSecrets:
  {{- toYaml $pullSecrets | nindent 2 }}
{{- end -}}
{{- end -}}

{{/*
Render a value that may contain Helm template expressions (Bitnami pattern #5).
If the value contains {{ it is rendered through tpl, otherwise passed through.

Usage:
  {{ include "fastapi-chassis.tplvalues.render" (dict "value" .Values.someValue "context" $) }}
*/}}
{{- define "fastapi-chassis.tplvalues.render" -}}
{{- if typeIs "string" .value -}}
  {{- if contains "{{" .value -}}
    {{- tpl .value .context -}}
  {{- else -}}
    {{- .value -}}
  {{- end -}}
{{- else -}}
  {{- tpl (.value | toYaml) .context -}}
{{- end -}}
{{- end -}}

{{/*
Return the target Kubernetes version, allowing override via values (Bitnami pattern #7).

Usage:
  {{ include "fastapi-chassis.capabilities.kubeVersion" . }}
*/}}
{{- define "fastapi-chassis.capabilities.kubeVersion" -}}
{{- default .Capabilities.KubeVersion.Version .Values.kubeVersionOverride -}}
{{- end -}}

{{/*
Return the appropriate apiVersion for Ingress.
*/}}
{{- define "fastapi-chassis.capabilities.ingress.apiVersion" -}}
{{- if semverCompare ">=1.19-0" (include "fastapi-chassis.capabilities.kubeVersion" .) -}}
networking.k8s.io/v1
{{- else if semverCompare ">=1.14-0" (include "fastapi-chassis.capabilities.kubeVersion" .) -}}
networking.k8s.io/v1beta1
{{- else -}}
extensions/v1beta1
{{- end -}}
{{- end -}}

{{/*
Return the appropriate apiVersion for HPA.
*/}}
{{- define "fastapi-chassis.capabilities.hpa.apiVersion" -}}
{{- if semverCompare ">=1.23-0" (include "fastapi-chassis.capabilities.kubeVersion" .) -}}
autoscaling/v2
{{- else -}}
autoscaling/v2beta2
{{- end -}}
{{- end -}}

{{/*
Return the appropriate apiVersion for PDB.
*/}}
{{- define "fastapi-chassis.capabilities.pdb.apiVersion" -}}
{{- if semverCompare ">=1.21-0" (include "fastapi-chassis.capabilities.kubeVersion" .) -}}
policy/v1
{{- else -}}
policy/v1beta1
{{- end -}}
{{- end -}}

{{/*
Return the appropriate apiVersion for CronJob.
*/}}
{{- define "fastapi-chassis.capabilities.cronjob.apiVersion" -}}
{{- if semverCompare ">=1.21-0" (include "fastapi-chassis.capabilities.kubeVersion" .) -}}
batch/v1
{{- else -}}
batch/v1beta1
{{- end -}}
{{- end -}}

{{/*
Return resource requests/limits, resolving preset vs explicit values (Bitnami pattern #8).
Explicit resources take precedence over presets.

Usage:
  {{- include "fastapi-chassis.resources" (dict "resources" .Values.resources "resourcePreset" (.Values.resourcePreset | default "")) | nindent 8 }}
*/}}
{{- define "fastapi-chassis.resources" -}}
{{- if .resources -}}
  {{- toYaml .resources -}}
{{- else if .resourcePreset -}}
  {{- include "fastapi-chassis.resources.preset" (dict "preset" .resourcePreset) -}}
{{- else -}}
{}
{{- end -}}
{{- end -}}

{{/*
Return predefined resource requests/limits for a given preset size.
These are intended for development/testing only — set explicit resources for production.

Presets: nano, micro, small, medium, large, xlarge, 2xlarge
*/}}
{{- define "fastapi-chassis.resources.preset" -}}
{{- if eq .preset "nano" -}}
requests:
  cpu: 50m
  memory: 64Mi
  ephemeral-storage: 50Mi
limits:
  memory: 128Mi
  ephemeral-storage: 1Gi
{{- else if eq .preset "micro" -}}
requests:
  cpu: 100m
  memory: 128Mi
  ephemeral-storage: 50Mi
limits:
  memory: 256Mi
  ephemeral-storage: 1Gi
{{- else if eq .preset "small" -}}
requests:
  cpu: 100m
  memory: 256Mi
  ephemeral-storage: 50Mi
limits:
  memory: 512Mi
  ephemeral-storage: 2Gi
{{- else if eq .preset "medium" -}}
requests:
  cpu: 250m
  memory: 512Mi
  ephemeral-storage: 50Mi
limits:
  memory: 1Gi
  ephemeral-storage: 2Gi
{{- else if eq .preset "large" -}}
requests:
  cpu: 500m
  memory: 1Gi
  ephemeral-storage: 50Mi
limits:
  memory: 2Gi
  ephemeral-storage: 4Gi
{{- else if eq .preset "xlarge" -}}
requests:
  cpu: 1000m
  memory: 2Gi
  ephemeral-storage: 50Mi
limits:
  memory: 4Gi
  ephemeral-storage: 8Gi
{{- else if eq .preset "2xlarge" -}}
requests:
  cpu: 2000m
  memory: 4Gi
  ephemeral-storage: 50Mi
limits:
  memory: 8Gi
  ephemeral-storage: 16Gi
{{- else -}}
{{- fail (printf "Invalid resource preset: %s. Valid values: nano, micro, small, medium, large, xlarge, 2xlarge" .preset) -}}
{{- end -}}
{{- end -}}

{{/*
Return affinity rules (Bitnami pattern #10).
If explicit affinity is set (non-empty map), use it.
Otherwise, generate pod anti-affinity from podAntiAffinityType (soft/hard).

Usage:
  {{- include "fastapi-chassis.affinity" . | nindent 4 }}
*/}}
{{- define "fastapi-chassis.affinity" -}}
{{- if gt (len (.Values.affinity | default dict)) 0 -}}
  {{- toYaml .Values.affinity -}}
{{- else if .Values.podAntiAffinityType -}}
  {{- if eq .Values.podAntiAffinityType "soft" }}
podAntiAffinity:
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            {{- include "fastapi-chassis.selectorLabels" . | nindent 12 }}
        topologyKey: kubernetes.io/hostname
  {{- else if eq .Values.podAntiAffinityType "hard" }}
podAntiAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          {{- include "fastapi-chassis.selectorLabels" . | nindent 10 }}
      topologyKey: kubernetes.io/hostname
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Resolve storage class from global and persistence-specific settings (Bitnami pattern #4).
Supports "-" to explicitly use the default storage class.

Usage:
  {{- include "fastapi-chassis.storage.class" (dict "persistence" .Values.persistence "global" (.Values.global | default dict)) }}
*/}}
{{- define "fastapi-chassis.storage.class" -}}
{{- $storageClass := .persistence.storageClass | default "" -}}
{{- if .global -}}
  {{- if .global.storageClass -}}
    {{- $storageClass = .global.storageClass -}}
  {{- end -}}
{{- end -}}
{{- if $storageClass -}}
  {{- if eq $storageClass "-" }}
storageClassName: ""
  {{- else }}
storageClassName: {{ $storageClass | quote }}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Pod template spec shared between Deployment and StatefulSet.
Takes a dict with keys: root (the top-level context) and isSqlite (bool string).
*/}}
{{- define "fastapi-chassis.podSpec" -}}
{{- $isLitefs := and (eq .isSqlite "true") .root.Values.litefs.enabled -}}
{{- $isLitestream := and (eq .isSqlite "true") .root.Values.litestream.enabled -}}
{{- $global := .root.Values.global | default dict -}}
metadata:
  annotations:
    checksum/config: {{ include (print $.root.Template.BasePath "/configmap.yaml") .root | sha256sum }}
    {{- if .root.Values.secret.create }}
    checksum/secret: {{ include (print $.root.Template.BasePath "/secret.yaml") .root | sha256sum }}
    {{- end }}
    {{- with .root.Values.podAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  labels:
    {{- include "fastapi-chassis.labels" .root | nindent 4 }}
    {{- with .root.Values.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- include "fastapi-chassis.imagePullSecrets" .root | nindent 2 }}
  serviceAccountName: {{ include "fastapi-chassis.serviceAccountName" .root }}
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  {{- if .root.Values.terminationGracePeriodSeconds }}
  terminationGracePeriodSeconds: {{ .root.Values.terminationGracePeriodSeconds }}
  {{- end }}
  {{- if .root.Values.topologySpreadConstraints }}
  topologySpreadConstraints:
    {{- toYaml .root.Values.topologySpreadConstraints | nindent 4 }}
  {{- end }}
  {{- if or $isLitefs $isLitestream }}
  initContainers:
    {{- if $isLitefs }}
    - name: litefs-init
      image: {{ include "fastapi-chassis.image" (dict "imageRoot" .root.Values.litefs.image "global" $global "defaultTag" "") }}
      command: ["cp", "/usr/local/bin/litefs", "/litefs-bin/litefs"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        requests:
          cpu: 10m
          memory: 16Mi
        limits:
          memory: 32Mi
      volumeMounts:
        - name: litefs-bin
          mountPath: /litefs-bin
    {{- end }}
    {{- if $isLitestream }}
    - name: litestream-restore
      image: {{ include "fastapi-chassis.image" (dict "imageRoot" .root.Values.litestream.image "global" $global "defaultTag" "") }}
      args: ["restore", "-if-db-not-exists", "-if-replica-exists", "-o", "/app/data/app.db", "{{ .root.Values.litestream.replica.url }}"]
      {{- if .root.Values.litestream.existingSecret }}
      envFrom:
        - secretRef:
            name: {{ .root.Values.litestream.existingSecret }}
      {{- end }}
      {{- with .root.Values.litestream.env }}
      env:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        requests:
          cpu: 50m
          memory: 64Mi
        limits:
          memory: 128Mi
      volumeMounts:
        - name: data
          mountPath: /app/data
    {{- end }}
  {{- end }}
  containers:
    - name: {{ .root.Chart.Name }}
      image: {{ include "fastapi-chassis.image" (dict "imageRoot" .root.Values.image "global" $global "defaultTag" .root.Chart.AppVersion) }}
      imagePullPolicy: {{ .root.Values.image.pullPolicy }}
      {{- if $isLitefs }}
      command: ["/litefs-bin/litefs", "mount"]
      {{- end }}
      ports:
        - name: http
          containerPort: {{ include "fastapi-chassis.exposedPort" .root }}
          protocol: TCP
        {{- if $isLitefs }}
        - name: litefs
          containerPort: 20202
          protocol: TCP
        {{- end }}
      envFrom:
        - configMapRef:
            name: {{ include "fastapi-chassis.fullname" .root }}
        {{- if .root.Values.secret.create }}
        - secretRef:
            name: {{ include "fastapi-chassis.fullname" .root }}
        {{- end }}
        {{- if .root.Values.existingSecret }}
        - secretRef:
            name: {{ .root.Values.existingSecret }}
        {{- end }}
        {{- with .root.Values.extraEnvFrom }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- $hasExistingSecretEnv := or (and (eq (.root.Values.database.backend | default "postgres") "postgres") .root.Values.database.postgres.existingSecret) (and (eq (.root.Values.database.backend | default "postgres") "custom") .root.Values.database.existingSecret) .root.Values.redis.existingSecret (and .root.Values.auth.enabled .root.Values.auth.existingSecret) -}}
      {{- if $hasExistingSecretEnv }}
      env:
        {{- if and (eq (.root.Values.database.backend | default "postgres") "postgres") .root.Values.database.postgres.existingSecret }}
        - name: APP_DATABASE_POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.database.postgres.existingSecret }}
              key: {{ .root.Values.database.postgres.existingSecretPasswordKey | default "APP_DATABASE_POSTGRES_PASSWORD" }}
        {{- end }}
        {{- if and (eq (.root.Values.database.backend | default "postgres") "custom") .root.Values.database.existingSecret }}
        - name: APP_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.database.existingSecret }}
              key: {{ .root.Values.database.existingSecretUrlKey | default "APP_DATABASE_URL" }}
        - name: APP_ALEMBIC_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.database.existingSecret }}
              key: {{ .root.Values.database.existingSecretAlembicUrlKey | default "APP_ALEMBIC_DATABASE_URL" }}
              optional: true
        {{- end }}
        {{- if .root.Values.redis.existingSecret }}
        - name: APP_REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.redis.existingSecret }}
              key: {{ .root.Values.redis.existingSecretPasswordKey | default "APP_REDIS_PASSWORD" }}
        {{- end }}
        {{- if and .root.Values.auth.enabled .root.Values.auth.existingSecret }}
        - name: APP_AUTH_JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.auth.existingSecret }}
              key: {{ .root.Values.auth.existingSecretJwtSecretKey | default "APP_AUTH_JWT_SECRET" }}
              optional: true
        - name: APP_AUTH_JWT_PUBLIC_KEY
          valueFrom:
            secretKeyRef:
              name: {{ .root.Values.auth.existingSecret }}
              key: {{ .root.Values.auth.existingSecretJwtPublicKeyKey | default "APP_AUTH_JWT_PUBLIC_KEY" }}
              optional: true
        {{- end }}
      {{- end }}
      livenessProbe:
        httpGet:
          path: {{ .root.Values.app.healthCheckPath | default "/healthcheck" }}
          port: http
        initialDelaySeconds: {{ .root.Values.probes.liveness.initialDelaySeconds | default 15 }}
        periodSeconds: {{ .root.Values.probes.liveness.periodSeconds | default 30 }}
        timeoutSeconds: {{ .root.Values.probes.liveness.timeoutSeconds | default 5 }}
        failureThreshold: {{ .root.Values.probes.liveness.failureThreshold | default 3 }}
        successThreshold: 1
      readinessProbe:
        httpGet:
          path: {{ .root.Values.app.readinessCheckPath | default "/ready" }}
          port: http
        initialDelaySeconds: {{ .root.Values.probes.readiness.initialDelaySeconds | default 5 }}
        periodSeconds: {{ .root.Values.probes.readiness.periodSeconds | default 10 }}
        timeoutSeconds: {{ .root.Values.probes.readiness.timeoutSeconds | default 5 }}
        failureThreshold: {{ .root.Values.probes.readiness.failureThreshold | default 3 }}
        successThreshold: 1
      startupProbe:
        httpGet:
          path: {{ .root.Values.app.healthCheckPath | default "/healthcheck" }}
          port: http
        initialDelaySeconds: {{ .root.Values.probes.startup.initialDelaySeconds | default 5 }}
        periodSeconds: {{ .root.Values.probes.startup.periodSeconds | default 5 }}
        timeoutSeconds: {{ .root.Values.probes.startup.timeoutSeconds | default 3 }}
        failureThreshold: {{ .root.Values.probes.startup.failureThreshold | default 12 }}
        successThreshold: 1
      resources:
        {{- include "fastapi-chassis.resources" (dict "resources" .root.Values.resources "resourcePreset" (.root.Values.resourcePreset | default "")) | nindent 8 }}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
          {{- if $isLitefs }}
          add:
            - SYS_ADMIN
          {{- end }}
      volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: var-tmp
          mountPath: /var/tmp
        {{- if eq .isSqlite "true" }}
        - name: data
          mountPath: /app/data
        {{- end }}
        {{- if $isLitefs }}
        - name: litefs-bin
          mountPath: /litefs-bin
          readOnly: true
        - name: litefs-fuse
          mountPath: /litefs
        - name: litefs-config
          mountPath: /etc/litefs.yml
          subPath: litefs.yml
        - name: dev-fuse
          mountPath: /dev/fuse
        {{- end }}
        {{- with .root.Values.extraVolumeMounts }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    {{- if $isLitestream }}
    - name: litestream
      image: {{ include "fastapi-chassis.image" (dict "imageRoot" .root.Values.litestream.image "global" $global "defaultTag" "") }}
      args: ["replicate"]
      {{- if .root.Values.litestream.existingSecret }}
      envFrom:
        - secretRef:
            name: {{ .root.Values.litestream.existingSecret }}
      {{- end }}
      {{- with .root.Values.litestream.env }}
      env:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        {{- toYaml (.root.Values.litestream.resources | default (dict "requests" (dict "cpu" "50m" "memory" "64Mi") "limits" (dict "memory" "128Mi"))) | nindent 8 }}
      volumeMounts:
        - name: data
          mountPath: /app/data
        - name: litestream-config
          mountPath: /etc/litestream.yml
          subPath: litestream.yml
    {{- end }}
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 64Mi
    - name: var-tmp
      emptyDir:
        sizeLimit: 64Mi
    {{- if $isLitefs }}
    - name: litefs-bin
      emptyDir:
        sizeLimit: 32Mi
    - name: litefs-fuse
      emptyDir: {}
    - name: litefs-config
      configMap:
        name: {{ include "fastapi-chassis.fullname" .root }}-litefs
    - name: dev-fuse
      hostPath:
        path: /dev/fuse
        type: CharDevice
    {{- end }}
    {{- if $isLitestream }}
    - name: litestream-config
      configMap:
        name: {{ include "fastapi-chassis.fullname" .root }}-litestream
    {{- end }}
    {{- with .root.Values.extraVolumes }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .root.Values.nodeSelector }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- $affinity := include "fastapi-chassis.affinity" .root -}}
  {{- if $affinity }}
  affinity:
    {{- $affinity | nindent 4 }}
  {{- end }}
  {{- with .root.Values.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
