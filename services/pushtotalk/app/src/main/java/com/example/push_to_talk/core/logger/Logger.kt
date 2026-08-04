package com.example.push_to_talk.core.logger

/**
 * Централизованное логирование. Слои приложения не обращаются к [android.util.Log] напрямую,
 * что позволяет подменять реализацию в тестах и подключать удалённые сборщики логов.
 */
interface Logger {
    fun d(tag: String, message: String)
    fun i(tag: String, message: String)
    fun w(tag: String, message: String, throwable: Throwable? = null)
    fun e(tag: String, message: String, throwable: Throwable? = null)
}
