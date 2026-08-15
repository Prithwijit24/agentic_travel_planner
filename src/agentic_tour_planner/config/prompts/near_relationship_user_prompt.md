Place A: {name_a} (category: {category_a})
Tags A: {tags_a}

Place B: {name_b} (category: {category_b})
Tags B: {tags_b}

Return JSON with exactly these keys:
- "rel_type": one of: "same_theme" (share a dominant theme), "complementary" (different but pair well on an itinerary), "nearby_only" (geographically close but thematically unrelated)
- "shared_tags": list of tags they share (subset of the intersection)
- "description": one sentence describing their relationship for a traveler
