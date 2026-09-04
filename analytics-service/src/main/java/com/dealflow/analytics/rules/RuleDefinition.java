package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.JsonNode;

public record RuleDefinition(
        long id,
        String code,
        String name,
        String description,
        String severity,
        JsonNode condition,
        boolean enabled,
        String lastValidationError) {}
