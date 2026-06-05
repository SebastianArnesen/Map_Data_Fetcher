# Bump when cached enrichment payload shape changes and rows must be rebuilt once.
# v4: capabilities.map_selection_layer (Open map button for Cell areas).
ENRICHMENT_VERSION = 4

# Background enrichment: modest parallelism to stay polite to Geonorge APIs.
ENRICH_MAX_WORKERS = 5
ENRICH_BATCH_SIZE = 75
ENRICH_PROGRESS_INTERVAL = 3
