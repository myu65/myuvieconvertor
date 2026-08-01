# Inference image

The repository-root `Dockerfile` is the canonical inference image. It installs all runtime
dependencies during build and forces Hugging Face and Transformers offline at runtime.
GitHub Actions builds it as `linux/amd64` and tags it with the immutable commit SHA.
