package com.example.push_to_talk.domain.model

/**
 * Полный домен ошибок приложения. Каждый сценарий сбоя имеет собственный тип,
 * поэтому UI и логика принимают решения без разбора строк и кодов платформы.
 */
sealed interface AppError {

    /** Ошибки распознавания речи. */
    sealed interface Speech : AppError {
        /** На устройстве нет доступного RecognitionService. */
        data object RecognizerUnavailable : Speech

        /** Микрофон недоступен или занят другим приложением. */
        data object MicrophoneUnavailable : Speech

        /** Разрешение RECORD_AUDIO не выдано. */
        data object PermissionDenied : Speech

        /** Речь не распознана: тишина или пустой результат. */
        data object NoSpeechDetected : Speech

        /** Пользователь молчал дольше допустимого. */
        data object SpeechTimeout : Speech

        /** Предыдущая сессия распознавания ещё не завершена. */
        data object RecognizerBusy : Speech

        /** Сессия отменена пользователем или системой. */
        data object Cancelled : Speech

        /** Ошибка на стороне клиента распознавания. */
        data object Client : Speech

        /** Ошибка на стороне сервиса распознавания. */
        data object Server : Speech

        /** Нет сети для облачного распознавания. */
        data object Network : Speech

        /** Таймаут сетевого распознавания. */
        data object NetworkTimeout : Speech

        /** Язык не поддерживается или языковой пакет не загружен. */
        data object LanguageUnavailable : Speech

        /** Слишком много запросов к сервису распознавания. */
        data object TooManyRequests : Speech

        /** Неизвестный код ошибки платформы. */
        data class Unknown(val code: Int) : Speech
    }

    /** Ошибки сетевого слоя. */
    sealed interface Network : AppError {
        /** Сеть недоступна: нет маршрута, DNS не отвечает, соединение оборвалось. */
        data object NoConnection : Network

        /** Сервер не ответил за отведённое время. */
        data object Timeout : Network

        /** Клиентская ошибка: сервер отверг запрос (4xx). */
        data class Http(val code: Int) : Network

        /** Сбой на стороне сервера (5xx) — запрос можно повторить позже. */
        data class Server(val code: Int) : Network

        /** Ответ не удалось разобрать: контракт разошёлся с backend-ом. */
        data object Serialization : Network

        data class Unexpected(val message: String) : Network
    }

    /** Ошибки валидации входных данных. */
    sealed interface Validation : AppError {
        data object EmptyText : Validation
    }
}
