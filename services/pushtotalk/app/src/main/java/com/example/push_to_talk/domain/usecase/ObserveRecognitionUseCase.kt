package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.domain.repository.SpeechRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject

/**
 * Доступ к состоянию и событиям распознавания.
 * [session] — состояние для отрисовки, [events] — разовые сигналы для побочных эффектов.
 */
class ObserveRecognitionUseCase @Inject constructor(
    private val speechRepository: SpeechRepository,
) {
    fun session(): StateFlow<RecognitionSession> = speechRepository.session

    fun events(): Flow<SpeechEvent> = speechRepository.events
}
