# Persistent model storage

Cloud Run's container filesystem is not the durable store for trained models. This deployment mounts a dedicated Google Cloud Storage bucket at `/app/models` using Cloud Run's Cloud Storage volume support. Google documents this as a supported Cloud Run volume type; the service identity needs object write permission for training. citeturn0search0

The deployment uses one Cloud Run instance and concurrency 1 because model writes are ordinary filesystem writes and Cloud Storage FUSE does not provide concurrency control for simultaneous writes to the same file. citeturn0search0

Do not run multiple writers against the same model object. If you later scale the API horizontally, introduce versioned model artifacts/object keys and an explicit model registry instead of allowing concurrent replacement of the same file.
