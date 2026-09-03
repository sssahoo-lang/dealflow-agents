package com.dealflow.analytics.dto;

import java.math.BigDecimal;

/**
 * @param winRate        won / (won + lost) within the window; null when nothing closed
 * @param avgDaysToClose creation to won transition; null when this rep won nothing
 */
public record LeaderboardRow(
        long ownerId,
        String ownerName,
        String ownerEmail,
        int dealsWon,
        int dealsLost,
        BigDecimal wonValue,
        BigDecimal openValue,
        Double winRate,
        Double avgDaysToClose) {}
