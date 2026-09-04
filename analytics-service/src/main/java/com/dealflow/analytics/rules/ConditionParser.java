package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * Parses the stored JSON into a {@link Condition} tree.
 *
 * <p>Validation happens here, at load and on update, rather than mid-sweep: a
 * malformed rule should be rejected when someone saves it, not discovered as a
 * silent no-op hours later.
 */
public final class ConditionParser {

    private ConditionParser() {}

    public static Condition parse(JsonNode node) {
        if (node == null || node.isNull() || !node.isObject()) {
            throw new IllegalArgumentException("Condition must be a JSON object");
        }

        if (node.has("all")) {
            return new Condition.All(parseList(node.get("all"), "all"));
        }
        if (node.has("any")) {
            return new Condition.Any(parseList(node.get("any"), "any"));
        }
        if (node.has("not")) {
            return new Condition.Not(parse(node.get("not")));
        }
        return parseComparison(node);
    }

    private static List<Condition> parseList(JsonNode node, String key) {
        if (!node.isArray()) {
            throw new IllegalArgumentException("'" + key + "' must be an array");
        }
        List<Condition> conditions = new ArrayList<>();
        for (JsonNode child : node) {
            conditions.add(parse(child));
        }
        return List.copyOf(conditions);
    }

    private static Condition parseComparison(JsonNode node) {
        JsonNode field = node.get("field");
        JsonNode op = node.get("op");
        if (field == null || !field.isTextual()) {
            throw new IllegalArgumentException("Comparison needs a textual 'field'");
        }
        if (op == null || !op.isTextual()) {
            throw new IllegalArgumentException("Comparison needs a textual 'op'");
        }

        Operator operator = Operator.fromWire(op.asText())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Unknown operator '" + op.asText() + "'"));

        JsonNode value = node.get("value");
        boolean needsValue = operator != Operator.IS_NULL && operator != Operator.NOT_NULL;
        if (needsValue && (value == null || value.isNull())) {
            throw new IllegalArgumentException(
                    "Operator '" + operator.wire() + "' requires a 'value'");
        }
        if ((operator == Operator.IN || operator == Operator.NOT_IN)
                && (value == null || !value.isArray())) {
            throw new IllegalArgumentException(
                    "Operator '" + operator.wire() + "' requires an array 'value'");
        }

        return new Condition.Comparison(field.asText(), operator, value);
    }
}
