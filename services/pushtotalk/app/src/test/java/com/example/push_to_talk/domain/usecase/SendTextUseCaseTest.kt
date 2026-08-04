package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.fake.FakeNetworkGateway
import com.example.push_to_talk.fake.errorOrFail
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SendTextUseCaseTest {

    private val network = FakeNetworkGateway()
    private val useCase = SendTextUseCase(network)

    @Test
    fun `успешная отправка возвращает Success`() = runTest {
        val result = useCase("hello")

        assertTrue(result.isSuccess)
        assertEquals(listOf("hello"), network.sentTexts)
    }

    @Test
    fun `отправляет обрезанный текст`() = runTest {
        val result = useCase("  привет мир  ")

        assertTrue(result.isSuccess)
        assertEquals(listOf("привет мир"), network.sentTexts)
    }

    @Test
    fun `пустой текст не доходит до сети`() = runTest {
        val result = useCase("")

        assertEquals(AppError.Validation.EmptyText, result.errorOrFail())
        assertEquals(0, network.callCount)
    }

    @Test
    fun `текст из одних пробелов не доходит до сети`() = runTest {
        val result = useCase("   \n\t ")

        assertEquals(AppError.Validation.EmptyText, result.errorOrFail())
        assertEquals(0, network.callCount)
    }

    @Test
    fun `ошибка сети возвращается вызывающему`() = runTest {
        network.result = failure(AppError.Network.NoConnection)

        val result = useCase("текст")

        assertEquals(AppError.Network.NoConnection, result.errorOrFail())
    }

    @Test
    fun `ошибка сервера возвращается вызывающему`() = runTest {
        network.result = failure(AppError.Network.Http(400))

        val result = useCase("текст")

        assertEquals(AppError.Network.Http(400), result.errorOrFail())
    }

    @Test
    fun `сбой сервера возвращается вызывающему`() = runTest {
        network.result = failure(AppError.Network.Server(500))

        val result = useCase("текст")

        assertEquals(AppError.Network.Server(500), result.errorOrFail())
    }

    @Test
    fun `таймаут возвращается вызывающему`() = runTest {
        network.result = failure(AppError.Network.Timeout)

        val result = useCase("текст")

        assertEquals(AppError.Network.Timeout, result.errorOrFail())
    }
}
