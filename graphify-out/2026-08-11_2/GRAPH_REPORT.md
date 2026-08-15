# Graph Report - .  (2026-08-10)

## Corpus Check
- 107 files · ~96,452 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1250 nodes · 2069 edges · 105 communities (63 shown, 42 thin omitted)
- Extraction: 79% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 435 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_API Client|API Client]]
- [[_COMMUNITY_Map Tool|Map Tool]]
- [[_COMMUNITY_Pipeline Core|Pipeline Core]]
- [[_COMMUNITY_API Client Tests|API Client Tests]]
- [[_COMMUNITY_API Events|API Events]]
- [[_COMMUNITY_CLI Plan Renderer|CLI Plan Renderer]]
- [[_COMMUNITY_AI Stack Client Tests|AI Stack Client Tests]]
- [[_COMMUNITY_Pipeline Agent|Pipeline Agent]]
- [[_COMMUNITY_Image Sources|Image Sources]]
- [[_COMMUNITY_Day Clustering|Day Clustering]]
- [[_COMMUNITY_Streamlit App|Streamlit App]]
- [[_COMMUNITY_Skills Lock|Skills Lock]]
- [[_COMMUNITY_AI Stack Client|AI Stack Client]]
- [[_COMMUNITY_Output Builder|Output Builder]]
- [[_COMMUNITY_Domain Models|Domain Models]]
- [[_COMMUNITY_Image Pipeline E2E|Image Pipeline E2E]]
- [[_COMMUNITY_AI Infra Integration|AI Infra Integration]]
- [[_COMMUNITY_LLM Provider|LLM Provider]]
- [[_COMMUNITY_LLM Hooks|LLM Hooks]]
- [[_COMMUNITY_Pipeline Prompts|Pipeline Prompts]]
- [[_COMMUNITY_API Images|API Images]]
- [[_COMMUNITY_DDGS Tooling|DDGS Tooling]]
- [[_COMMUNITY_Geonames Index|Geonames Index]]
- [[_COMMUNITY_LLM Error Handling|LLM Error Handling]]
- [[_COMMUNITY_News Service|News Service]]
- [[_COMMUNITY_Planning Workers|Planning Workers]]
- [[_COMMUNITY_Image Cache Tests|Image Cache Tests]]
- [[_COMMUNITY_Planning API Models|Planning API Models]]
- [[_COMMUNITY_API Main|API Main]]
- [[_COMMUNITY_LLM Provider Tests|LLM Provider Tests]]
- [[_COMMUNITY_Image Models|Image Models]]
- [[_COMMUNITY_Image Processor Tests|Image Processor Tests]]
- [[_COMMUNITY_Output Format|Output Format]]
- [[_COMMUNITY_Cost Estimator|Cost Estimator]]
- [[_COMMUNITY_Image Processor|Image Processor]]
- [[_COMMUNITY_Planning Domain Models|Planning Domain Models]]
- [[_COMMUNITY_LLM Provider Chain|LLM Provider Chain]]
- [[_COMMUNITY_Image Models Tests|Image Models Tests]]
- [[_COMMUNITY_Config Settings|Config Settings]]
- [[_COMMUNITY_CLI LLM Filter|CLI LLM Filter]]
- [[_COMMUNITY_Images Tests|Images Tests]]
- [[_COMMUNITY_Image Cache Dedup|Image Cache Dedup]]
- [[_COMMUNITY_Image Stack|Image Stack]]
- [[_COMMUNITY_Travel Constraints|Travel Constraints]]
- [[_COMMUNITY_Image Result Tests|Image Result Tests]]
- [[_COMMUNITY_Provider Test Script|Provider Test Script]]
- [[_COMMUNITY_Loading Animations|Loading Animations]]
- [[_COMMUNITY_Image Pipeline Tests|Image Pipeline Tests]]
- [[_COMMUNITY_LLM Walltime Test|LLM Walltime Test]]
- [[_COMMUNITY_LLM Provider Models|LLM Provider Models]]
- [[_COMMUNITY_Image Pipeline|Image Pipeline]]
- [[_COMMUNITY_AI Stack Init|AI Stack Init]]
- [[_COMMUNITY_Image Settings Tests|Image Settings Tests]]
- [[_COMMUNITY_Logging Utils|Logging Utils]]
- [[_COMMUNITY_World Map Animation|World Map Animation]]
- [[_COMMUNITY_Pulse Animation|Pulse Animation]]
- [[_COMMUNITY_AI Stack Mock Tests|AI Stack Mock Tests]]
- [[_COMMUNITY_AI Stack Lifecycle Tests|AI Stack Lifecycle Tests]]
- [[_COMMUNITY_App Init|App Init]]
- [[_COMMUNITY_CLI Init|CLI Init]]
- [[_COMMUNITY_Config Init|Config Init]]
- [[_COMMUNITY_Images Init|Images Init]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Pipeline Init|Pipeline Init]]
- [[_COMMUNITY_AI Stack Cache Set|AI Stack Cache Set]]
- [[_COMMUNITY_AI Stack CLIP Image|AI Stack CLIP Image]]
- [[_COMMUNITY_AI Stack CLIP Similarity|AI Stack CLIP Similarity]]
- [[_COMMUNITY_AI Stack CLIP Text|AI Stack CLIP Text]]
- [[_COMMUNITY_AI Stack Embed|AI Stack Embed]]
- [[_COMMUNITY_AI Stack Graph Edge|AI Stack Graph Edge]]
- [[_COMMUNITY_AI Stack Graph Node|AI Stack Graph Node]]
- [[_COMMUNITY_AI Stack Search|AI Stack Search]]
- [[_COMMUNITY_AI Stack Storage Delete|AI Stack Storage Delete]]
- [[_COMMUNITY_AI Stack Storage Download|AI Stack Storage Download]]
- [[_COMMUNITY_AI Stack Vector Delete|AI Stack Vector Delete]]
- [[_COMMUNITY_AI Stack Vector Upsert|AI Stack Vector Upsert]]
- [[_COMMUNITY_AI Stack YouTube Audio|AI Stack YouTube Audio]]
- [[_COMMUNITY_AI Stack Browse|AI Stack Browse]]
- [[_COMMUNITY_AI Stack News|AI Stack News]]
- [[_COMMUNITY_AI Stack Videos|AI Stack Videos]]
- [[_COMMUNITY_AI Stack Vector Search|AI Stack Vector Search]]
- [[_COMMUNITY_AI Stack YouTube Info|AI Stack YouTube Info]]
- [[_COMMUNITY_AI Stack YouTube Transcript|AI Stack YouTube Transcript]]
- [[_COMMUNITY_AI Stack YouTube Thumbnail|AI Stack YouTube Thumbnail]]
- [[_COMMUNITY_AI Stack DuckDB Query|AI Stack DuckDB Query]]
- [[_COMMUNITY_AI Stack Storage List|AI Stack Storage List]]
- [[_COMMUNITY_AI Stack DuckDB Insert|AI Stack DuckDB Insert]]
- [[_COMMUNITY_AI Stack DuckDB Tables|AI Stack DuckDB Tables]]
- [[_COMMUNITY_Tools Init|Tools Init]]
- [[_COMMUNITY_LLM Provider Config|LLM Provider Config]]
- [[_COMMUNITY_Map Tool Config|Map Tool Config]]
- [[_COMMUNITY_CLI Plan Config|CLI Plan Config]]
- [[_COMMUNITY_Pipeline Fallback|Pipeline Fallback]]
- [[_COMMUNITY_Pipeline Realign|Pipeline Realign]]
- [[_COMMUNITY_Pipeline Transport|Pipeline Transport]]
- [[_COMMUNITY_Pipeline Context|Pipeline Context]]
- [[_COMMUNITY_Profiler Utils|Profiler Utils]]
- [[_COMMUNITY_Profiler Config|Profiler Config]]

## God Nodes (most connected - your core abstractions)
1. `AiStackClient` - 65 edges
2. `LLMProvider` - 62 edges
3. `ApiClient` - 62 edges
4. `_make_client()` - 36 edges
5. `MapTool` - 35 edges
6. `get_settings()` - 25 edges
7. `AgenticTourPlannerPipeline` - 22 edges
8. `PlanningRequest` - 22 edges
9. `_mock_response()` - 21 edges
10. `TestApiClientCore` - 19 edges

## Surprising Connections (you probably didn't know these)
- `_api_key_configured()` --calls--> `LLMProvider`  [INFERRED]
  tests/integration/test_llm_walltime.py → src/agentic_tour_planner/llm/provider.py
- `test_image_result_with_image()` --calls--> `ImageResult`  [INFERRED]
  tests/unit/test_image_models.py → src/agentic_tour_planner/images/models.py
- `TestAiStackClientCore` --uses--> `AiStackClient`  [INFERRED]
  tests/unit/test_ai_stack_client.py → src/agentic_tour_planner/tools/ai_stack_client.py
- `TestAiStackClientCLIP` --uses--> `AiStackClient`  [INFERRED]
  tests/unit/test_ai_stack_client.py → src/agentic_tour_planner/tools/ai_stack_client.py
- `TestAiStackClientCache` --uses--> `AiStackClient`  [INFERRED]
  tests/unit/test_ai_stack_client.py → src/agentic_tour_planner/tools/ai_stack_client.py

## Hyperedges (group relationships)
- **Pre-commit Quality Gates** — ruff_linter, mypy_type_checker, detect_secrets_hook, bandit_scanner, hadolint_docker_linter, compose_schema_validator, env_file_guard, conventional_commit_linter [EXTRACTED 1.00]
- **Runtime Surfaces** — fastapi_backend, streamlit_ui, tour_planner_cli [EXTRACTED 1.00]
- **Image Pipeline Stages** — image_source_waterfall, clip_relevance_scoring, nsfw_content_moderation, perceptual_hash_dedup, image_redis_cache [EXTRACTED 1.00]
- **** — output_format_core_places, output_format_optional_places, output_format_n_places_per_day [INFERRED]
- **** — output_format_keywords_array, output_format_keyword_categories, output_format_cli_renderer [INFERRED]

## Communities (105 total, 42 thin omitted)

### Community 0 - "API Client"
Cohesion: 0.07
Nodes (6): ApiClient, AI Infra Stack — Python API client (curl-style wrapper)., Base class: curl-like wrapper around the AI Infra Stack API., POST /images — image search with optional CLIP reranking.          Fallback chai, POST /news — fetch recent news articles about a topic.          Returns ``{"resu, POST /videos — search YouTube videos about a topic.          Returns ``{"results

### Community 1 - "Map Tool"
Cohesion: 0.06
Nodes (28): _haversine_km(), _hex_color(), MapTool, Resilient map tool with per-place geocoding fallback, zoom-based tile switching,, Render an interactive map with markers for each day's activities.          Uses, Extract locations from itinerary and geocode them per-place.          Prioritize, Detect and fix duplicate or suspiciously close coordinates.          When differ, Geocode without destination bias for accuracy validation. (+20 more)

### Community 2 - "Pipeline Core"
Cohesion: 0.06
Nodes (52): Agentic Pipeline Module, Agentic Travel Planner, Agnes Provider, annotate_travel_constraints Function, API-CLI Parity Plan, API-CLI Parity Design Spec, API Configuration, API Streaming and UI Integration Plan (+44 more)

### Community 3 - "API Client Tests"
Cohesion: 0.08
Nodes (13): _make_client(), _mock_response(), Unit tests for the synchronous ApiClient wrapper., Create a mock httpx.Response., Create an ApiClient with a mock httpx.Client., TestApiClientAuth, TestApiClientCore, TestApiClientErrors (+5 more)

### Community 4 - "API Events"
Cohesion: 0.07
Nodes (33): EventEmitter, _evict_emitters(), get_emitter(), _prune_emitters(), Collects log events during pipeline execution for SSE streaming., register_emitter(), remove_emitter(), create_feedback() (+25 more)

### Community 5 - "CLI Plan Renderer"
Cohesion: 0.08
Nodes (47): _apply_emphasis(), attach(), _clean_meal(), _highlight_keywords(), _highlight_names(), _highlight_times(), interactive(), _is_meal() (+39 more)

### Community 6 - "AI Stack Client Tests"
Cohesion: 0.04
Nodes (8): Unit tests for the async AiStackClient wrapper., TestAiStackClientCache, TestAiStackClientCLIP, TestAiStackClientCore, TestAiStackClientDuckDB, TestAiStackClientGraph, TestAiStackClientStorage, TestAiStackClientYouTube

### Community 7 - "Pipeline Agent"
Cohesion: 0.06
Nodes (22): TransportOption, AgenticTourPlannerPipeline, _day_centroid_moved(), _dedupe_detailed_days(), _dedupe_key(), _fallback_places(), Generate the detailed, place-by-place itinerary as structured data., Normalized matching key for a place name: lowercase, and trailing     '(optional (+14 more)

### Community 8 - "Image Sources"
Cohesion: 0.06
Nodes (34): _commons_imageinfo_to_candidates(), fetch_ddgs_images(), fetch_mapillary(), fetch_openverse(), fetch_stack_images(), fetch_stock(), fetch_wikidata(), fetch_wikimedia_commons() (+26 more)

### Community 9 - "Day Clustering"
Cohesion: 0.07
Nodes (23): balanced_geo_cluster(), _closest_pair(), haversine(), order_days_and_stops(), day_clustering.py ================= Deterministic module for splitting a list of, Nearest-neighbor construction + 2-opt improvement. Returns index order., 1. Orders the days themselves into a sensible travel sequence        (nearest-ne, Great-circle distance in km between two (lat, lon) points. (+15 more)

### Community 10 - "Streamlit App"
Cohesion: 0.08
Nodes (35): _build_provider_models(), _build_request_from_form(), _call_plans_api(), clean_html(), _fetch_images(), fluent_card(), html_escape(), _load_loading_svg() (+27 more)

### Community 11 - "Skills Lock"
Cohesion: 0.05
Nodes (37): computedHash, skillPath, source, sourceType, computedHash, skillPath, source, sourceType (+29 more)

### Community 12 - "AI Stack Client"
Cohesion: 0.07
Nodes (16): AiStackClient, POST /crawl — extract clean markdown from a URL., POST /pipeline — search -> crawl -> rerank (non-streaming)., POST /pipeline/stream — SSE streaming pipeline. Returns iterator., POST /rerank — cross-encoder relevance ranking., POST /images — image search with optional CLIP reranking.          Fallback chai, Thin async wrapper around the AI Infra Stack ApiClient.      All methods return, GET /cache/get/{key} — read a value from Redis. (+8 more)

### Community 13 - "Output Builder"
Cohesion: 0.17
Nodes (27): build_output(), Shared output builder for CLI and API to ensure consistent output structure., Check that each place description is approximately TARGET_DESCRIPTION_WORDS., Build the unified output dictionary used by both CLI and API.      This ensures, _validate_place_word_counts(), _make_context(), _make_detailed(), _make_insights() (+19 more)

### Community 14 - "Domain Models"
Cohesion: 0.14
Nodes (22): BaseModel, Citation, CostEstimate, CostLineItem, DailyCost, DayWeather, DetailedDay, DetailedPlace (+14 more)

### Community 15 - "Image Pipeline E2E"
Cohesion: 0.14
Nodes (21): _make_candidate(), _make_processed(), End-to-end integration test for the destination image pipeline.  Tests the full, When Wikidata returns nothing, pipeline should try Wikimedia Commons, then Wikip, When no source returns candidates, pipeline returns an empty ImageResult., When processing rejects all candidates from source 1, pipeline tries source 2., Each place in the list is resolved independently with its own waterfall., When a source raises an exception, pipeline should catch it and try the next sou (+13 more)

### Community 16 - "AI Infra Integration"
Cohesion: 0.11
Nodes (21): AI Infra Stack Integration Plan, AI Infra Stack Integration Design Spec, AI Infra Stack, AI Infra Stack Base URL, AiStackClient Async Wrapper, ApiClient Module, Shared App Data Volume, Bandit Security Scanner (+13 more)

### Community 17 - "LLM Provider"
Cohesion: 0.15
Nodes (13): LLMProvider, Minimal OpenAI-compatible LLM provider with simple failure routing.      Calls p, All candidate models (planner + worker) declared for a provider, de-duplicated., test_explicit_request_provider_overrides_fallback_chain(), test_get_planner_and_worker_model_return_preferred(), test_llm_unavailable_when_no_providers_configured(), test_marked_down_provider_is_filtered_out(), test_model_override_is_tried_before_provider_defaults() (+5 more)

### Community 18 - "LLM Hooks"
Cohesion: 0.13
Nodes (7): CallMetrics, MetricsBus, Accumulates token usage across all LLM calls., Accumulates wall-clock time spent in LLM calls, per provider., Shared bus that the two hooks write to; readable by the CLI/API., TimeEstimateHook, TokenCounterHook

### Community 19 - "Pipeline Prompts"
Cohesion: 0.16
Nodes (16): build_day_realign_prompt(), build_detailed_places_prompt(), _format_live_brief(), _is_real_place_name(), _load_output_format_spec(), Build the prompt for the detailed place-by-place markdown itinerary.      Uses t, Heuristic guard against logistics/day-phase labels masquerading as spots.      R, Build the prompt that realigns one day's theme/summary/hotel with the     solver (+8 more)

### Community 20 - "API Images"
Cohesion: 0.15
Nodes (13): collect_places_for_images(), _place_type_hint(), Infer the place's physical type from its name ("" when unknown)., Extract place dicts from a PlanningResponse itinerary for image resolution., SpotDetail, Tests for the rewritten api/images.py module., The LLM's place-restricted image_query wins over name fallback., Without an LLM query, an ambiguous name (Hanuman Tok = monkey god)         is an (+5 more)

### Community 21 - "DDGS Tooling"
Cohesion: 0.17
Nodes (18): CLIP Relevance Scoring, DDGS Extract Crawler Fallback, DDGS Live News Fallback, DDGS Image Source Fetcher, DDGS Primary Tooling Plan, DDGS Primary Tooling Design Spec, DDGS Search Cascade Flip, Destination Image Pipeline Plan (+10 more)

### Community 22 - "Geonames Index"
Cohesion: 0.20
Nodes (15): _search_suggestions(), _add_name(), _build_index(), _get_index(), _load_index(), _next_id(), _save_index(), search_places() (+7 more)

### Community 23 - "LLM Error Handling"
Cohesion: 0.15
Nodes (11): _classify_error(), _content_of(), _is_gateway_error_content(), _payload_for(), Build the request body for a provider, adapting non-OpenAI formats., Extract the assistant text from a response body, adapting non-OpenAI formats., Put a hard-failing provider on cooldown so it is skipped promptly.          Serv, Reset the failure streak when a provider answers successfully. (+3 more)

### Community 24 - "News Service"
Cohesion: 0.16
Nodes (10): NewsArticle, NewsDigest, NewsService, Fetch and summarize recent news about a destination.  Uses the AI Infra Stack /n, LLM generates a 3-5 sentence overview., LLM generates a 1-2 sentence summary., Fetch and summarize recent news about a destination.      Uses the AI Infra Stac, Try fetching news from AI Infra Stack /news endpoint. (+2 more)

### Community 25 - "Planning Workers"
Cohesion: 0.20
Nodes (7): BudgetPlannerWorker, _heuristic(), PlanningInsightsBuilder, Validate LLM-produced fields into a pydantic model. If the model output     pars, RoutePlannerWorker, _safe_build(), TimingPlannerWorker

### Community 26 - "Image Cache Tests"
Cohesion: 0.14
Nodes (15): get_cached_image(), Retrieve a cached image result by place_id. Returns None if disabled or miss., Unit tests for image cache layer (AiStackClient-based)., get_dedup_hashes should return empty list when Redis is disabled., get_dedup_hashes should return stored hashes., add_dedup_hash should append a new hash to the existing list., Cache should return None when Redis is disabled., Cache should return None on cache miss. (+7 more)

### Community 27 - "Planning API Models"
Cohesion: 0.15
Nodes (10): PlanningRequest, PlanningResponse, StoredPlanRecord, _make_plan_with_spots(), test_create_plan_returns_plan_api_response(), test_get_plan_images_skips_spots_without_image_query(), test_run_plan_job_streams_completed_plan(), test_planning_request_requires_destination() (+2 more)

### Community 28 - "API Main"
Cohesion: 0.19
Nodes (15): get_plan_images(), ImageResponse, LogEvent, PlanAPIResponse, A single event in the SSE stream., Validated response the UI maps from., _make_planning_response(), test_image_response() (+7 more)

### Community 29 - "LLM Provider Tests"
Cohesion: 0.15
Nodes (7): _FakeAsyncClient, _FakeResponse, Minimal httpx.AsyncClient replacement. ``post`` may sleep to simulate a     gate, A gateway that accepts the request but never completes the body must be     cut, HTTP 200 with an empty body is a failure: fail over instead of wasting     the n, test_empty_content_marks_provider_down(), test_hard_deadline_cuts_off_trickling_gateway()

### Community 30 - "Image Models"
Cohesion: 0.18
Nodes (12): ImageCandidate, ProcessedImage, Pydantic models for the destination image pipeline., An image that has passed post-processing., A raw candidate image from a source, before validation., Unit tests for image pipeline models., test_image_candidate_full(), test_image_candidate_minimal() (+4 more)

### Community 31 - "Image Processor Tests"
Cohesion: 0.20
Nodes (13): _make_image_bytes(), _make_test_image(), Unit tests for image post-processing pipeline (AiStackClient-based)., process_image should skip duplicates based on content hash., Create a simple test image of given dimensions., Create test image bytes of given dimensions., process_image should return None for images below min resolution., process_image should return ProcessedImage for valid images (mocking CLIP). (+5 more)

### Community 32 - "Output Format"
Cohesion: 0.19
Nodes (13): CLI Renderer, Core Places (mandatory, is_optional: false), Day Object (day, theme, places), Days Array, Detailed Place-by-Place Itinerary Output Format, Emphasis Formatting (bold, italics), Itinerary JSON Schema, Keyword Categories (place, altitude, person, deity, other) (+5 more)

### Community 33 - "Cost Estimator"
Cohesion: 0.29
Nodes (11): CostEstimator, cost_estimator.py ================= Deterministic travel cost estimation for a g, _ticket_price(), _make_request(), _plan(), Tests for the deterministic cost estimator.  The estimator is computed from the, test_caps_daily_cost_at_8000_per_person(), test_deterministic_estimate_matches_price_table() (+3 more)

### Community 34 - "Image Processor"
Cohesion: 0.18
Nodes (12): _clip_score(), _compute_image_hash(), process_image(), Image post-processing: quality filter, CLIP scoring, dedup, NSFW, smart crop.  U, # TODO: Add NSFW check when stack supports it, Compute CLIP relevance score via AI Infra Stack /clip/similarity endpoint., Compute a content hash for deduplication., Download, quality-filter, CLIP-score, dedup, and crop a candidate image.      Re (+4 more)

### Community 35 - "Planning Domain Models"
Cohesion: 0.38
Nodes (11): BudgetGuidance, PlanningInsights, RetrievedContext, RouteGuidance, TimingGuidance, _make_plan_response(), build_itinerary_prompt(), _response_with_spots() (+3 more)

### Community 36 - "LLM Provider Chain"
Cohesion: 0.24
Nodes (5): _extract_json(), Filter a (provider, model) chain to only the providers not on cooldown., Per-provider timeout override from llm.yml (e.g. a slow self-hosted         mode, Build the (provider, model) attempt order. An explicit provider selection is, Single free-text completion (no JSON parsing). Used for translation and

### Community 37 - "Image Models Tests"
Cohesion: 0.18
Nodes (11): Resolve images for a list of places using the multi-source pipeline.      Each d, resolve_images(), PlaceImage, test_get_plan_images_returns_images(), Tests for extended PlaceImage model., New fields should be settable., Old code creating PlaceImage with 4 fields should still work., test_place_image_backward_compatible() (+3 more)

### Community 38 - "Config Settings"
Cohesion: 0.29
Nodes (8): _coerce_env_overrides(), get_settings(), _is_secret_field(), _load_env_variables(), _load_yaml_configs(), Configuration loaded entirely from per-module YAML files.      Every attribute i, _resolve_path(), Settings

### Community 39 - "CLI LLM Filter"
Cohesion: 0.20
Nodes (6): _LiteLLMFilter, LogLevel, Suppress non-critical LiteLLM logging worker timeout errors., LLMUnavailableError, Discover provider configs from settings: any dict attribute that looks         l, StrEnum

### Community 40 - "Images Tests"
Cohesion: 0.20
Nodes (9): Tests for agentic_tour_planner.api.images — updated for the new multi-source pip, resolve_images should map ImageResult objects to PlaceImage objects., When the pipeline returns a result with no URL, PlaceImage should have image_url, resolve_images should return empty list for empty input., resolve_images should handle multiple places correctly., test_resolve_images_empty_list(), test_resolve_images_handles_failure(), test_resolve_images_multiple_places() (+1 more)

### Community 41 - "Image Cache Dedup"
Cohesion: 0.29
Nodes (9): add_dedup_hash(), get_dedup_hashes(), _hash_key(), Cache layer for the destination image pipeline.  Uses AI Infra Stack /cache endp, Add a content hash to the dedup set for a place., Retrieve existing content hashes for a place., Try each source in order, return the first one that passes processing., _run_waterfall() (+1 more)

### Community 42 - "Image Stack"
Cohesion: 0.20
Nodes (9): _cache_key(), Store an image result in the cache., set_cached_image(), get_ai_stack(), Shared AiStackClient singleton for the images module., Get or create the shared AiStackClient singleton., set_cached_image should store the result in cache., test_cache_key_format() (+1 more)

### Community 43 - "Travel Constraints"
Cohesion: 0.31
Nodes (8): DayPlan, annotate_travel_constraints(), lookup_travel_leg(), TravelLeg, test_day_plan_accepts_rationale(), test_detailed_prompt_contains_dedupe_and_plain_name_rules(), test_annotates_long_adjacent_leg(), test_annotates_over_daily_travel_budget()

### Community 44 - "Image Result Tests"
Cohesion: 0.22
Nodes (9): ImageResult, Final result for a single place., When a cached result exists, pipeline should return it without calling any sourc, test_cache_hit_skips_waterfall(), api.images.resolve_images should delegate to images.pipeline.resolve_images., Pipeline results with None fields should map correctly., test_resolve_images_delegates_to_pipeline(), test_resolve_images_handles_none_fields() (+1 more)

### Community 45 - "Provider Test Script"
Cohesion: 0.36
Nodes (7): main(), _print_result(), Per-provider connectivity test harness for the Agentic Travel Planner LLM layer., Probe a single provider (its worker + planner model(s)) and report results., Exercise the real fallback router end-to-end and report what it produced., test_fallback_chain(), test_provider()

### Community 46 - "Loading Animations"
Cohesion: 0.38
Nodes (7): SVG Clip Path Definitions, Notification Color Palette, Fade In Opacity Animation, Notification Card Element, Notifications SVG Loading Animation, Slide Down Translate Animation, SMIL Animation System

### Community 47 - "Image Pipeline Tests"
Cohesion: 0.29
Nodes (5): Integration tests for the image pipeline orchestrator., Pipeline should return no image when all sources fail., Pipeline should return cached result when available., test_resolve_images_returns_no_image_when_all_sources_fail(), test_resolve_images_uses_cache_when_available()

### Community 48 - "LLM Walltime Test"
Cohesion: 0.47
Nodes (5): _api_key_configured(), Live wall-time check for the direct-httpx LLM provider.  The point of removing l, _run(), test_real_llm_call_recorded_in_metrics(), test_real_llm_call_wall_time()

### Community 50 - "Image Pipeline"
Cohesion: 0.33
Nodes (5): _place_id(), Pipeline orchestrator: wires sources → processor → cache., Generate a cache key from place name (and optional coordinates)., Resolve images for a list of places.      Each dict should have at least 'place_, resolve_images()

### Community 51 - "AI Stack Init"
Cohesion: 0.40
Nodes (3): Async wrapper around self-hosted AI Infra Stack., Return setting value if non-empty, else fall back to env_var., _resolve_credential()

### Community 52 - "Image Settings Tests"
Cohesion: 0.40
Nodes (4): clear_config(), Unit tests for image pipeline settings., Image pipeline settings should have sensible defaults., test_image_settings_defaults()

### Community 53 - "Logging Utils"
Cohesion: 0.50
Nodes (4): configure_logging(), get_logger(), Configure the single global loguru sink. Idempotent unless an explicit     ``lev, Return a loguru logger bound with the module ``name`` for easy debugging.

### Community 54 - "World Map Animation"
Cohesion: 0.50
Nodes (4): Landmass Region i1, Landmass Region i2, Landmass Region i3, World Map SVG

### Community 55 - "Pulse Animation"
Cohesion: 1.00
Nodes (4): Pulse Circle, Ring Group, Stroke Style Group, Pulse SVG Root

### Community 56 - "AI Stack Mock Tests"
Cohesion: 0.50
Nodes (4): client_with_mock(), _mock_api_client(), Create a mock ApiClient with sensible defaults., Create an AiStackClient with a mocked ApiClient.

## Knowledge Gaps
- **58 isolated node(s):** `version`, `source`, `sourceType`, `skillPath`, `computedHash` (+53 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AiStackClient` connect `AI Stack Client` to `API Client`, `API Events`, `AI Stack Client Tests`, `Pipeline Agent`, `News Service`, `Image Stack`, `AI Stack Init`, `AI Stack Mock Tests`, `AI Stack Lifecycle Tests`, `AI Stack Cache Set`, `AI Stack CLIP Image`, `AI Stack CLIP Similarity`, `AI Stack CLIP Text`, `AI Stack Embed`, `AI Stack Graph Edge`, `AI Stack Graph Node`, `AI Stack Search`, `AI Stack Storage Delete`, `AI Stack Storage Download`, `AI Stack Vector Delete`, `AI Stack Vector Upsert`, `AI Stack YouTube Audio`, `AI Stack Browse`, `AI Stack News`, `AI Stack Videos`, `AI Stack Vector Search`, `AI Stack YouTube Info`, `AI Stack YouTube Transcript`, `AI Stack YouTube Thumbnail`, `AI Stack DuckDB Query`, `AI Stack Storage List`, `AI Stack DuckDB Insert`, `AI Stack DuckDB Tables`?**
  _High betweenness centrality (0.273) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Config Settings` to `Image Processor`, `API Events`, `CLI Plan Renderer`, `CLI LLM Filter`, `Image Sources`, `Image Cache Dedup`, `Image Stack`, `Pipeline Agent`, `Streamlit App`, `AI Stack Init`, `Image Settings Tests`, `Logging Utils`, `Image Cache Tests`?**
  _High betweenness centrality (0.240) - this node is a cross-community bridge._
- **Why does `LLMProvider` connect `LLM Provider` to `LLM Provider Chain`, `CLI Plan Renderer`, `CLI LLM Filter`, `Pipeline Agent`, `Streamlit App`, `Provider Test Script`, `LLM Walltime Test`, `LLM Provider Models`, `LLM Hooks`, `LLM Error Handling`, `News Service`, `Planning Workers`, `LLM Provider Tests`?**
  _High betweenness centrality (0.195) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `AiStackClient` (e.g. with `TestAiStackClientInit` and `TestAiStackClientLifecycle`) actually correct?**
  _`AiStackClient` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 37 inferred relationships involving `LLMProvider` (e.g. with `_FakeResponse` and `_FakeAsyncClient`) actually correct?**
  _`LLMProvider` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `ApiClient` (e.g. with `TestApiClientInit` and `TestApiClientLifecycle`) actually correct?**
  _`ApiClient` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `version`, `source`, `sourceType` to the rest of the system?**
  _343 weakly-connected nodes found - possible documentation gaps or missing edges._
