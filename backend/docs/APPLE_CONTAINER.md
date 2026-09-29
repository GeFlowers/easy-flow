# Apple Container Support

DeerFlow now supports Apple Container as the preferred container runtime on macOS, with automatic fallback to Docker.

## Overview

Starting with this version, DeerFlow automatically detects and uses Apple Container on macOS when available, falling back to Docker when:
- Apple Container is not installed
- Running on non-macOS platforms

This provides better performance on Apple Silicon Macs while maintaining compatibility across all platforms.

## Benefits

### On Apple Silicon Macs with Apple Container:
- **Better Performance**: Native ARM64 execution without Rosetta 2 translation
- **Lower Resource Usage**: Lighter weight than Docker Desktop
- **Native Integration**: Uses macOS Virtualization.framework

### Fallback to Docker:
- Full backward compatibility
- Works on all platforms (macOS, Linux, Windows)
- No configuration changes needed

## Requirements

### For Apple Container (macOS only):
- macOS 15.0 or later
- Apple Silicon (M1/M2/M3/M4)
- Apple Container CLI installed

### Installation:
```bash
# Download from GitHub releases
# https://github.com/apple/container/releases

# Verify installation
container --version

# Start the service
container system start
```

### For Docker (all platforms):
- Docker Desktop or Docker Engine

## How It Works

### Automatic Detection

The `AioSandboxProvider` automatically detects the available container runtime:

1. On macOS: Try `container --version`
   - Success → Use Apple Container
   - Failure → Fall back to Docker

2. On other platforms: Use Docker directly

### Runtime Differences

Both runtimes use nearly identical command syntax:

**Container Startup:**
```bash
# Apple Container
container run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image

# Docker
docker run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image
```

**Container Cleanup:**
```bash
# Apple Container (with --rm flag)
container stop <id>  # Auto-removes due to --rm

# Docker (with --rm flag)
docker stop <id>     # Auto-removes due to --rm
```

### Implementation Details

The implementation is in `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`:

- `_detect_container_runtime()`: Detects available runtime at startup
- `_start_container()`: Uses detected runtime, skips Docker-specific options for Apple Container
- `_stop_container()`: Uses appropriate stop command for the runtime

## Configuration

No configuration changes are needed! The system works automatically.

However, you can verify the runtime in use by checking the logs:

```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Detected Apple Container: container version 0.1.0
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using container: ...
```

Or for Docker:
```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Apple Container not available, falling back to Docker
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using docker: ...
```

## Container Images

Both runtimes use OCI-compatible images. The default image works with both:

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest  # Default image
```

Make sure your images are available for the appropriate architecture:
- ARM64 for Apple Container on Apple Silicon
- AMD64 for Docker on Intel Macs
- Multi-arch images work on both

### Pre-pulling Images

**Important**: Container images are typically large (500MB+) and are pulled on first use, which can cause a long wait time without clear feedback.

When using this optional container sandbox, you may pull the image manually:

```bash
# Using Apple Container
container image pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# Using Docker
docker pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
```

If you skip pre-pulling, the image will be automatically pulled on first agent execution, which may take several minutes depending on your network speed.

## Cleanup

`make docker-stop` stops the application containers. It does not manage
containers created by an alternate sandbox provider; use that provider's
runtime tools to inspect or remove them.

## Testing

Test the container runtime detection:

```bash
cd backend
python test_container_runtime.py
```

This will:
1. Detect the available runtime
2. Optionally start a test container
3. Verify connectivity
4. Clean up

## Troubleshooting

### Apple Container not detected on macOS

1. Check if installed:
   ```bash
   which container
   container --version
   ```

2. Check if service is running:
   ```bash
   container system start
   ```

3. Check logs for detection:
   ```bash
   # Look for detection message in application logs
   grep "container runtime" logs/*.log
   ```

### Containers not cleaning up

1. Manually check running containers:
   ```bash
   # Apple Container
   container list

   # Docker
   docker ps
   ```

2. Remove only verified, unused DeerFlow sandbox containers with the selected
   runtime's own container-management command.

### Performance issues

- Apple Container should be faster on Apple Silicon
- If experiencing issues, you can force Docker by temporarily renaming the `container` command:
   ```bash
   # Temporary workaround - not recommended for permanent use
   sudo mv /opt/homebrew/bin/container /opt/homebrew/bin/container.bak
   ```

## References

- [Apple Container GitHub](https://github.com/apple/container)
- [Apple Container Documentation](https://github.com/apple/container/blob/main/docs/)
- [OCI Image Spec](https://github.com/opencontainers/image-spec)
