package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.fake.FakePermissionChecker
import com.example.push_to_talk.fake.FakeSpeechRepository
import com.example.push_to_talk.fake.errorOrFail
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StartRecognitionUseCaseTest {

    private val speechRepository = FakeSpeechRepository()
    private val permissionChecker = FakePermissionChecker()
    private val useCase = StartRecognitionUseCase(speechRepository, permissionChecker)

    @Test
    fun `запускает распознавание при выданном разрешении`() = runTest {
        val result = useCase()

        assertTrue(result.isSuccess)
        assertEquals(1, speechRepository.startCount)
    }

    @Test
    fun `без разрешения распознавание не запускается`() = runTest {
        permissionChecker.granted = false

        val result = useCase()

        assertEquals(AppError.Speech.PermissionDenied, result.errorOrFail())
        assertEquals(0, speechRepository.startCount)
    }

    @Test
    fun `повторный запуск во время активной сессии отклоняется`() = runTest {
        speechRepository.setSession(RecognitionSession(status = RecognitionStatus.Listening))

        val result = useCase()

        assertEquals(AppError.Speech.RecognizerBusy, result.errorOrFail())
        assertEquals(0, speechRepository.startCount)
    }
}
