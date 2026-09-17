# Service package boundaries

This directory contains server-side packages. Dependencies flow from transport handlers through application use cases and pure domain code to consumed ports and outer adapters. WP-00 defines only the dependency-free health transport and the opaque `IdGenerator` protocol. Feature behavior and feature ports are deferred to their owning work packages.

Reserved package directories are markers only until their approved work package introduces code.
