# Bump when cached enrichment payload shape changes and rows must be rebuilt once.
# v4: capabilities.map_selection_layer (Open map button for Cell areas).
# v5: per-area formats_by_projection (projection→format compatibility).
# v6: intersect formats_by_projection when merging duplicate area rows from API.
ENRICHMENT_VERSION = 6

# Background enrichment: modest parallelism to stay polite to Geonorge APIs.
ENRICH_MAX_WORKERS = 5
ENRICH_BATCH_SIZE = 75
ENRICH_PROGRESS_INTERVAL = 3

# Download packaging: max concurrent Geonorge orders being prepared server-side.
MAX_SERVER_ORDERS = 2
ORDER_POLL_INTERVAL_S = 2.5
ORDER_CHUNK_SIZE = 20
# Parallel HTTP transfers once files are ready (packaging is separate).
MAX_PARALLEL_DOWNLOADS = 3
