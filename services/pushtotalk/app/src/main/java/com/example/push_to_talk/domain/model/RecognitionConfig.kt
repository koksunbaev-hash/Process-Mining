package com.example.push_to_talk.domain.model

/**
 * Параметры сессии распознавания. Значения по умолчанию рассчитаны на Push-to-Talk:
 * короткие реплики, промежуточные результаты включены, начало и конец речи определяет сам движок.
 */
data class RecognitionConfig(
    /** BCP-47 тег языка. `null` — язык по умолчанию из настроек устройства. */
    val languageTag: String? = null,

    /** Отдавать промежуточные результаты по мере распознавания. */
    val partialResults: Boolean = true,

    /** Пауза, после которой движок считает речь завершённой. */
    val silenceTimeoutMillis: Long = 1_500L,

    /** Минимальная длительность реплики, до которой пауза не учитывается. */
    val minimumSpeechLengthMillis: Long = 500L,

    /** Пауза до первого слова, после которой сессия завершается по таймауту. */
    val speechInputTimeoutMillis: Long = 5_000L,

    /** Предпочитать оффлайн-распознавание, если движок это поддерживает. */
    val preferOffline: Boolean = false,
)
