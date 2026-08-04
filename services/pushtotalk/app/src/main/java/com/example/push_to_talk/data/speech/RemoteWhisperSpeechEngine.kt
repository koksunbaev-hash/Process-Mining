package com.example.push_to_talk.data.speech

import android.content.Context
import android.media.MediaRecorder
import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.data.network.NetworkErrorMapper
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.SpeechEvent
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class RemoteWhisperSpeechEngine @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val apiService: ApiService,
    private val dispatchers: DispatcherProvider,
    private val logger: Logger,
) : SpeechEngine {

    private val _events = MutableSharedFlow<SpeechEvent>(
        extraBufferCapacity = EVENT_BUFFER_CAPACITY,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    override val events: Flow<SpeechEvent> = _events.asSharedFlow()

    private var recorder: MediaRecorder? = null
    private var activeFile: File? = null
    private var isRecording = false

    override fun isAvailable(): Boolean = true

    override suspend fun start(config: RecognitionConfig): AppResult<Unit> =
        withContext(dispatchers.io) {
            if (isRecording) {
                return@withContext failure(AppError.Speech.RecognizerBusy)
            }

            val output = File.createTempFile("ptt-whisper-", ".m4a", context.cacheDir)
            runCatching {
                emit(SpeechEvent.Preparing)
                recorder = createRecorder(output).also { it.start() }
                activeFile = output
                isRecording = true
                emit(SpeechEvent.ReadyForSpeech)
                emit(SpeechEvent.SpeechStarted)
            }.fold(
                onSuccess = { success() },
                onFailure = { throwable ->
                    logger.e(TAG, "Failed to start audio recording", throwable)
                    cleanupRecorder()
                    output.delete()
                    emit(SpeechEvent.Failed(AppError.Speech.MicrophoneUnavailable))
                    failure(AppError.Speech.MicrophoneUnavailable)
                },
            )
        }

    override suspend fun stop() {
        val file = withContext(dispatchers.io) {
            if (!isRecording) return@withContext null
            stopRecorder()
        } ?: return

        emit(SpeechEvent.SpeechEnded)
        transcribe(file)
    }

    override suspend fun cancel() {
        withContext(dispatchers.io) {
            cleanupRecorder()
            activeFile?.delete()
            activeFile = null
            isRecording = false
        }
        emit(SpeechEvent.Cancelled)
    }

    override suspend fun release() {
        cancel()
    }

    @Suppress("DEPRECATION")
    private fun createRecorder(output: File): MediaRecorder =
        MediaRecorder().apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setAudioChannels(1)
            setAudioSamplingRate(AUDIO_SAMPLE_RATE)
            setAudioEncodingBitRate(AUDIO_BIT_RATE)
            setOutputFile(output.absolutePath)
            prepare()
        }

    private fun stopRecorder(): File? {
        val file = activeFile
        runCatching { recorder?.stop() }
            .onFailure { logger.w(TAG, "Recorder stop failed: ${it.message}") }
        cleanupRecorder()
        activeFile = null
        isRecording = false
        return file?.takeIf { it.exists() && it.length() > 0L }
    }

    private fun cleanupRecorder() {
        runCatching { recorder?.reset() }
        runCatching { recorder?.release() }
        recorder = null
    }

    private suspend fun transcribe(file: File) {
        withContext(dispatchers.io) {
            try {
                val request = file.asRequestBody(AUDIO_MEDIA_TYPE)
                val part = MultipartBody.Part.createFormData("file", file.name, request)
                val response = apiService.transcribeAudio(part)
                val text = response.text.orEmpty().trim()
                if (!response.isAccepted || text.isEmpty()) {
                    emit(SpeechEvent.Failed(AppError.Speech.NoSpeechDetected))
                } else {
                    emit(SpeechEvent.FinalResult(text))
                }
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (throwable: Throwable) {
                val error = NetworkErrorMapper.toAppError(throwable).toSpeechError()
                logger.e(TAG, "Whisper transcription failed: $error", throwable)
                emit(SpeechEvent.Failed(error))
            } finally {
                file.delete()
            }
        }
    }

    private fun AppError.toSpeechError(): AppError.Speech = when (this) {
        AppError.Network.Timeout -> AppError.Speech.NetworkTimeout
        AppError.Network.NoConnection -> AppError.Speech.Network
        is AppError.Network.Http -> AppError.Speech.Client
        is AppError.Network.Server -> AppError.Speech.Server
        AppError.Network.Serialization -> AppError.Speech.Server
        is AppError.Network.Unexpected -> AppError.Speech.Server
        is AppError.Speech -> this
        is AppError.Validation -> AppError.Speech.Client
    }

    private fun emit(event: SpeechEvent) {
        if (!_events.tryEmit(event)) {
            logger.w(TAG, "Speech event buffer is full, event dropped: $event")
        }
    }

    private companion object {
        const val TAG = "RemoteWhisper"
        const val EVENT_BUFFER_CAPACITY = 64
        const val AUDIO_SAMPLE_RATE = 16_000
        const val AUDIO_BIT_RATE = 64_000
        val AUDIO_MEDIA_TYPE = "audio/mp4".toMediaType()
    }
}
