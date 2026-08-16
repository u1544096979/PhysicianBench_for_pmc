# Oncology CSV runtime

Build from the repository root:

```bash
docker build -f docker/oncology-csv/Dockerfile -t physicianbench-oncology-csv .
```

Mount the raw CSV and task directories read-only. The image does not contain the clinical data:

```bash
docker run --rm \
  -v "$PWD/data/oncology_complete_trajectory:/app/data/oncology_complete_trajectory:ro" \
  -v "$PWD/tasks/oncology-v1:/app/tasks/oncology-v1:ro" \
  physicianbench-oncology-csv tasks/oncology-v1/<case_id> --data-root /app/data/oncology_complete_trajectory
```
