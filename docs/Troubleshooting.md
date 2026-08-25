# Troubleshooting

## Environment Center shows BLOCK

Read the affected row first. Common causes are an incomplete model download, a checksum mismatch, an incompatible Runtime, missing support-layer dependencies, insufficient disk space, or a low Windows Free Commit value. Click **Recheck** after resolving the condition.

## A download was interrupted

Run **Install / Repair Everything** again. Completed files are verified and retained; partial downloads continue from their saved cache where the source supports ranges.

## An existing Runtime or Models Root is already installed

Use the path fields in Environment Center and choose **Use Existing Runtime** or **Use Existing Models**. The installer adopts only a layout that passes the pinned version, provenance and checksum checks; it does not overwrite an incompatible existing Runtime.

## Generation fails

Save the user-facing error and the application log. Do not delete model files or caches first. Open Advanced ComfyUI only for diagnostics. A GPU OOM on an experimental sub-24GB GPU is an unsupported hardware outcome, not a workflow repair instruction.

## The development ComfyUI is already running

On every normal start the launcher checks ports 8189 and 8788. If the port is
owned by a recognizable ComfyUI or Architect Video Studio process, it restarts
that stale process and waits briefly for the port to be released before
starting the managed instance. An unrelated process is never terminated; the
launcher reports its PID and asks you to close it or choose another supported
runtime.
