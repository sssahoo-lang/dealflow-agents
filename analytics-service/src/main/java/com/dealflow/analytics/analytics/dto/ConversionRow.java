package com.dealflow.analytics.dto;

/**
 * One step of the pipeline funnel.
 *
 * @param entered  deals that reached {@code fromStage} or beyond
 * @param advanced deals that reached {@code toStage} or beyond
 * @param rate     advanced / entered; null when nothing entered the stage
 */
public record ConversionRow(
        String fromStage, String toStage, long entered, long advanced, Double rate) {}
