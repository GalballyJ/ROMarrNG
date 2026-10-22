# ROMarr -- the *arr for games.
#
# Keep compiler headers in the builder, and use Debian in both stages so
# cryptography can use its published manylinux ARMv7 wheel. Alpine's musl
# target has no matching wheel; its source build tries to install a Rust host
# toolchain that rustup does not provide for 32-bit ARM.

FROM python:3.14-slim AS builder

# Build tools stay out of the runtime image. libseccomp-dev is what pyseccomp
# compiles against -- the sandbox ROM Hub confines plugins with.
# libffi-dev lets CFFI compile when pip has no wheel for the target Python/arch.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libseccomp-dev libffi-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# ROM Hub, the plugin host the Hub tab drives (issue #10: the image shipped
# the bridge but never the package, so Docker installs reported "rom_hub is
# missing" with nothing to be done about it). Pinned to a commit, because
# "whatever master was when the image built" is not a version.
RUN pip install --no-cache-dir --prefix=/install \
    "rom-hub @ https://github.com/BlizzHacker/rom-hub/archive/8e46348783546ee03b00e2c933155ba60d29619d.tar.gz"


FROM python:3.14-slim

ARG TARGETARCH

# gosu is su-exec's Debian twin; the shared entrypoint uses the same uid:gid
# command form on both images. tzdata makes TZ work.
#
# libarchive-tools provides bsdtar, which is what reads .7z and .rar. It is
# not optional cargo: the disc platforms this image now supports ship almost
# entirely as .7z, so without it every PlayStation, PS2 and Wii import fails
# on a format it cannot open. Alpine's busybox `tar` is not a substitute and
# is deliberately not accepted -- see romarr/library.py::_bsdtar.
# libseccomp is the runtime half of the sandbox pyseccomp was built against.
# ROM Hub installs catalogue plugins from pinned repository refs, so git is a
# runtime dependency rather than builder cargo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu tzdata libarchive-tools libseccomp2 git ca-certificates \
 && ln -s "$(command -v gosu)" /usr/local/bin/su-exec \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Importing the packages is not enough: the broken image imported ROM Hub and
# only failed when the Plugins page asked pyseccomp to find its C library. Load
# a real restrictive filter during the build so that exact failure cannot be
# published again.
# The CI smoke image is native amd64. The multi-arch publish that follows runs
# arm64 under QEMU, where seccomp_load is canceled by the emulator (errno 125)
# even though the same filter loads on native Docker. Prove the actual image on
# the native leg and do not mistake QEMU's build environment for arm64 runtime.
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      python -c "import rom_hub, pyseccomp; from rom_hub.sandbox import install; install()"; \
    fi

WORKDIR /app
COPY romarr/ /app/romarr/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /config /roms

# Paths chosen for the container, not the host. ROMARR_DATA is a file, so its
# directory is what gets mounted.
#
# LIBRARY_PATH is deliberately NOT set here. It has an older alias,
# ROMM_LIBRARY, and an image ENV beats the application's fallback chain -- so
# setting it here would silently ignore the ROMM_LIBRARY an existing install
# brought with it. The entrypoint defaults it only when neither name is given.
# ROM_HUB_HOME lives under /config so installed plugins survive a container
# recreation the same way settings do. The application default is a path
# inside the container filesystem, which silently loses every plugin on
# `docker compose pull`.
ENV ROMARR_DATA=/config/romarr.json \
    ROM_HUB_HOME=/config/rom-hub \
    ROMARR_HOST=0.0.0.0 \
    ROMARR_PORT=6868 \
    PUID=1000 \
    PGID=1000 \
    UMASK=002 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME /config
EXPOSE 6868

# Python is already here, so the healthcheck needs no curl. A non-200 raises.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('ROMARR_PORT','6868')+'/api/health',timeout=4)"

LABEL org.opencontainers.image.title="ROMarrNG" \
      org.opencontainers.image.description="ROMarrNG adds a SeerrNG request and library contract to ROMarr" \
      org.opencontainers.image.source="https://github.com/snapetech-org/ROMarrNG" \
      org.opencontainers.image.licenses="MIT"

# The entrypoint prepares only /config as root, then drops to PUID:PGID before
# running the app. A fixed Docker USER would break ownership for mounted config.
# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["/entrypoint.sh"]
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["python", "-m", "romarr"]
