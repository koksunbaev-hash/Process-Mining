package com.example.push_to_talk.core.dispatcher

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Абстракция над [Dispatchers], чтобы бизнес-логику можно было тестировать
 * на детерминированных тестовых диспетчерах.
 */
interface DispatcherProvider {
    /** Главный поток. Обязателен для всех вызовов [android.speech.SpeechRecognizer]. */
    val main: CoroutineDispatcher

    /** Главный поток без лишнего диспатча, если вызов уже происходит в нём. */
    val mainImmediate: CoroutineDispatcher

    val io: CoroutineDispatcher

    val default: CoroutineDispatcher
}

@Singleton
class DefaultDispatcherProvider @Inject constructor() : DispatcherProvider {
    override val main: CoroutineDispatcher = Dispatchers.Main
    override val mainImmediate: CoroutineDispatcher = Dispatchers.Main.immediate
    override val io: CoroutineDispatcher = Dispatchers.IO
    override val default: CoroutineDispatcher = Dispatchers.Default
}
