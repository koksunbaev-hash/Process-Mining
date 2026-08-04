package com.example.push_to_talk.data.network

import com.example.push_to_talk.domain.model.AppError
import kotlinx.serialization.SerializationException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class NetworkErrorMapperTest {

    @Test
    fun `таймаут сокета отображается в Timeout`() {
        assertEquals(
            AppError.Network.Timeout,
            NetworkErrorMapper.toAppError(SocketTimeoutException("read timed out")),
        )
    }

    @Test
    fun `прерванный ввод-вывод отображается в Timeout`() {
        assertEquals(
            AppError.Network.Timeout,
            NetworkErrorMapper.toAppError(InterruptedIOException("timeout")),
        )
    }

    @Test
    fun `неизвестный хост отображается в NoConnection`() {
        assertEquals(
            AppError.Network.NoConnection,
            NetworkErrorMapper.toAppError(UnknownHostException("ptt.invalid")),
        )
    }

    @Test
    fun `отказ в соединении отображается в NoConnection`() {
        assertEquals(
            AppError.Network.NoConnection,
            NetworkErrorMapper.toAppError(ConnectException("connection refused")),
        )
    }

    @Test
    fun `любая другая ошибка ввода-вывода отображается в NoConnection`() {
        assertEquals(
            AppError.Network.NoConnection,
            NetworkErrorMapper.toAppError(IOException("сокет закрыт")),
        )
    }

    @Test
    fun `код 400 отображается в Http`() {
        assertEquals(AppError.Network.Http(400), NetworkErrorMapper.toAppError(httpException(400)))
    }

    @Test
    fun `код 404 отображается в Http`() {
        assertEquals(AppError.Network.Http(404), NetworkErrorMapper.toAppError(httpException(404)))
    }

    @Test
    fun `код 499 остаётся клиентской ошибкой`() {
        assertEquals(AppError.Network.Http(499), NetworkErrorMapper.toAppError(httpException(499)))
    }

    @Test
    fun `код 500 отображается в Server`() {
        assertEquals(AppError.Network.Server(500), NetworkErrorMapper.toAppError(httpException(500)))
    }

    @Test
    fun `код 503 отображается в Server`() {
        assertEquals(AppError.Network.Server(503), NetworkErrorMapper.toAppError(httpException(503)))
    }

    @Test
    fun `сбой разбора ответа отображается в Serialization`() {
        assertEquals(
            AppError.Network.Serialization,
            NetworkErrorMapper.toAppError(SerializationException("неожиданный токен")),
        )
    }

    @Test
    fun `неизвестное исключение сохраняет сообщение`() {
        assertEquals(
            AppError.Network.Unexpected("что-то пошло не так"),
            NetworkErrorMapper.toAppError(IllegalStateException("что-то пошло не так")),
        )
    }

    @Test
    fun `неизвестное исключение без сообщения не падает`() {
        assertEquals(
            AppError.Network.Unexpected(""),
            NetworkErrorMapper.toAppError(IllegalStateException()),
        )
    }

    private fun httpException(code: Int): HttpException {
        val body = """{"status":"error"}""".toResponseBody("application/json".toMediaType())
        return HttpException(Response.error<Any>(code, body))
    }
}
