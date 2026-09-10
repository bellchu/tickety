apiVersion: batch/v1
kind: Job
metadata:
  name: @BACKUP_JOB@
  namespace: tickety
  labels:
    app.kubernetes.io/name: tickety
    app.kubernetes.io/component: backup
    app.kubernetes.io/environment: development
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app: tickety-backup
        app.kubernetes.io/name: tickety
        app.kubernetes.io/component: migration
        app.kubernetes.io/environment: development
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        fsGroup: 999
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: backup
          image: pgvector/pgvector:0.8.6-pg16
          imagePullPolicy: IfNotPresent
          command:
            - /bin/sh
            - -ec
            - |
              umask 077
              temporary="/backups/.@BACKUP_FILE@.tmp"
              destination="/backups/@BACKUP_FILE@"
              pg_dump --format=custom --host=postgres --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --file="$temporary"
              pg_restore --list "$temporary" >/dev/null
              mv "$temporary" "$destination"
          env:
            - {name: POSTGRES_USER, value: tickety}
            - {name: POSTGRES_DB, value: tickety}
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef: {name: tickety-secrets, key: POSTGRES_PASSWORD}
          resources:
            requests: {cpu: 50m, memory: 128Mi}
            limits: {cpu: 500m, memory: 512Mi}
          securityContext:
            runAsUser: 999
            runAsGroup: 999
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: backups, mountPath: /backups}
            - {name: tmp, mountPath: /tmp}
      volumes:
        - name: backups
          persistentVolumeClaim: {claimName: tickety-dev-backups}
        - name: tmp
          emptyDir: {sizeLimit: 64Mi}
