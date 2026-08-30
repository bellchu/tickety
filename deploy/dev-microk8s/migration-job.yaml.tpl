apiVersion: batch/v1
kind: Job
metadata:
  name: @MIGRATION_JOB@
  namespace: tickety
  labels:
    app.kubernetes.io/name: tickety
    app.kubernetes.io/component: migration
    app.kubernetes.io/environment: development
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app: tickety-migrate
        app.kubernetes.io/name: tickety
        app.kubernetes.io/component: migration
        app.kubernetes.io/environment: development
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        fsGroup: 10001
        seccompProfile: {type: RuntimeDefault}
      initContainers:
        - name: wait-for-postgres
          image: @BACKEND_IMAGE@
          imagePullPolicy: IfNotPresent
          envFrom:
            - secretRef: {name: tickety-secrets}
          command:
            - python
            - -c
            - |
              import os, time
              import psycopg2
              url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
              for _ in range(60):
                  try:
                      connection = psycopg2.connect(url)
                      connection.close()
                      break
                  except Exception:
                      time.sleep(2)
              else:
                  raise SystemExit("PostgreSQL did not become ready")
          resources:
            requests: {cpu: 25m, memory: 64Mi}
            limits: {cpu: 250m, memory: 256Mi}
          securityContext:
            runAsUser: 10001
            runAsGroup: 10001
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: tmp, mountPath: /tmp}
      containers:
        - name: migrate
          image: @BACKEND_IMAGE@
          imagePullPolicy: IfNotPresent
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef: {name: tickety-secrets}
          resources:
            requests: {cpu: 50m, memory: 128Mi}
            limits: {cpu: 500m, memory: 512Mi}
          securityContext:
            runAsUser: 10001
            runAsGroup: 10001
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: tmp, mountPath: /tmp}
      volumes:
        - name: tmp
          emptyDir: {sizeLimit: 64Mi}
