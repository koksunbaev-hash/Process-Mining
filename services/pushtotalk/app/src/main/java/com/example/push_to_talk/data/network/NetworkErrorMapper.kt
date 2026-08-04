package com.example.push_to_talk.data.network

import com.example.push_to_talk.domain.model.AppError
import kotlinx.serialization.SerializationException
import retrofit2.HttpException
import java.io.IOException
import java.io.InterruptedIOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Переводит исключения сетевого слоя в домен ошибок приложения.
 *
 * Это единственное место, где живут типы Retrofit/OkHttp/kotlinx: выше по стеку
 * ходят только [AppError], поэтому смена HTTP-клиента не затрагивает domain и UI.
 */
internal object NetworkErrorMapper {

    private const val SERVER_ERROR_MIN = 500

    fun toAppError(throwable: Throwable): AppError.Network = when (throwable) {
        // SocketTimeoutException — подкласс InterruptedIOException, поэтому проверяется первым.
        is SocketTimeoutException -> AppError.Network.Timeout
        is UnknownHostException -> AppError.Network.NoConnection
        is HttpException -> fromHttpCode(throwable.code())
        is SerializationException -> AppError.Network.Serialization
        // OkHttp сообщает о превышении `callTimeout` именно этим типом.
        is InterruptedIOException -> AppError.Network.Timeout
        is IOException -> AppError.Network.NoConnection
        else -> AppError.Network.Unexpected(throwable.message.orEmpty())
    }

    /** 5xx — сбой сервера, всё остальное считаем ошибкой запроса. */
    private fun fromHttpCode(code: Int): AppError.Network = if (code >= SERVER_ERROR_MIN) {
        AppError.Network.Server(code)
    } else {
        AppError.Network.Http(code)
    }
}
