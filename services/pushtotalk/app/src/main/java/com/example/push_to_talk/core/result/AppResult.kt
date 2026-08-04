package com.example.push_to_talk.core.result

import com.example.push_to_talk.domain.model.AppError

/**
 * Результат операции с типизированной ошибкой [AppError].
 * Используется вместо kotlin.Result, который не позволяет описать домен ошибок статически.
 */
sealed interface AppResult<out T> {

    data class Success<out T>(val data: T) : AppResult<T>

    data class Failure(val error: AppError) : AppResult<Nothing>

    val isSuccess: Boolean get() = this is Success

    fun getOrNull(): T? = (this as? Success)?.data

    fun errorOrNull(): AppError? = (this as? Failure)?.error
}

inline fun <T, R> AppResult<T>.map(transform: (T) -> R): AppResult<R> = when (this) {
    is AppResult.Success -> AppResult.Success(transform(data))
    is AppResult.Failure -> this
}

inline fun <T> AppResult<T>.onSuccess(action: (T) -> Unit): AppResult<T> = apply {
    if (this is AppResult.Success) action(data)
}

inline fun <T> AppResult<T>.onFailure(action: (AppError) -> Unit): AppResult<T> = apply {
    if (this is AppResult.Failure) action(error)
}

fun success(): AppResult<Unit> = AppResult.Success(Unit)

fun failure(error: AppError): AppResult<Nothing> = AppResult.Failure(error)
