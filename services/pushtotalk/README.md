# Push-to-Talk

Голосовой клиент Push-to-Talk на современном Android-стеке плюс backend, который принимает и
хранит распознанный текст. Пользователь нажимает круглую кнопку 🎤, приложение само определяет
начало и конец речи средствами системного `SpeechRecognizer`, показывает промежуточный и
финальный текст, отправляет результат на сервер и показывает «✅ Отправлено» либо
«❌ Ошибка отправки».

Проект спроектирован как фундамент для полноценного AI Voice Client: STT-движок, сетевой слой и
режим кнопки заменяются без изменения UI и бизнес-логики.

## Состав репозитория

```
.
├── app/        Android-клиент (Kotlin, Compose, MVVM + Clean Architecture)
├── backend/    FastAPI-сервис приёма текста (см. backend/README.md)
└── .github/    CI: тесты обеих частей, lint, сборка APK, сквозной сценарий
```

## Быстрый старт

```bash
# 1. Сервер
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080

# 2. Узнайте IP машины с сервером в вашей сети
ipconfig                                            # Linux/macOS: ip addr

# 3. Клиент: адрес backend-а задаётся параметром сборки
cd ..
./gradlew installDebug -PapiBaseUrl=http://192.168.0.137:8002/
```

Для эмулятора адрес хоста — `http://10.0.2.2:8080/`.

> **`❌ Ошибка отправки` / «нет соединения с сервером»** почти всегда означает неверный адрес.
> Проверьте по порядку: телефон в той же сети Wi-Fi; `uvicorn` запущен с `--host 0.0.0.0`;
> `apiBaseUrl` указывает на реальный IP машины с сервером; firewall пропускает входящие на
> порт 8080. Быстрая проверка с телефона — открыть `http://<ip>:8080/api/health` в браузере.

## Стек

| Слой | Технологии |
|------|-----------|
| UI | Jetpack Compose, Material 3, Navigation Compose (типобезопасные маршруты) |
| Презентация | MVVM, `ViewModel`, `StateFlow`, Unidirectional Data Flow |
| DI | Hilt (KSP) |
| Асинхронность | Kotlin Coroutines, Flow |
| Сеть | Retrofit 3, OkHttp 5, kotlinx.serialization |
| Backend | FastAPI, SQLAlchemy 2, Pydantic v2, SQLite |
| Тесты | JUnit 4, kotlinx-coroutines-test, MockWebServer, pytest + pytest-cov |
| Сборка | Gradle Kotlin DSL, Version Catalog (`gradle/libs.versions.toml`), AGP 9 со встроенной поддержкой Kotlin |

Минимальная версия Android — API 24, целевая и компиляционная — API 37.

## Архитектура

Clean Architecture с тремя слоями и строгими правилами зависимостей:

```
presentation ──► domain ◄── data
                  ▲
                core
```

- **presentation** знает только про use case-ы и модели domain. `MainViewModel` не имеет доступа к
  `Context` и ничего не знает про `SpeechRecognizer`.
- **domain** — чистый Kotlin: модели, интерфейсы репозиториев и use case-ы. Не зависит ни от
  Android-фреймворка, ни от Retrofit.
- **data** реализует интерфейсы domain и содержит всю работу с платформой и сетью.
- **core** — сквозная инфраструктура: логирование, диспетчеры корутин, проверка разрешений,
  тип результата `AppResult`.

### Структура пакетов

```
com.example.push_to_talk
├── core
│   ├── dispatcher   DispatcherProvider, DefaultDispatcherProvider
│   ├── logger       Logger, AndroidLogger
│   ├── permissions  PermissionChecker, AndroidPermissionChecker
│   └── result       AppResult (Success / Failure с типизированной ошибкой)
├── domain
│   ├── model        SpeechEvent, RecognitionSession, RecognitionStatus,
│   │                RecognitionConfig, AppError
│   ├── repository   SpeechRepository, NetworkRepository
│   └── usecase      Start/Stop/Cancel/ReleaseRecognitionUseCase,
│                    ObserveRecognitionUseCase, SendTextUseCase,
│                    CheckMicrophonePermissionUseCase
├── data
│   ├── speech       SpeechEngine, SpeechRecognitionManager,
│   │                AndroidSpeechRecognizerEngine, SpeechErrorMapper
│   ├── network      ApiService, NetworkErrorMapper, AuthInterceptor,
│   │                AuthTokenProvider, dto/SendTextDto, dto/SendTextResponseDto
│   └── repository   SpeechRepositoryImpl, RetrofitNetworkRepository,
│                    FakeNetworkRepository
├── di               CoreModule, RepositoryModule, NetworkModule,
│                    NetworkBindingsModule, @ApplicationScope
└── presentation
    ├── main         MainRoute, MainScreen, MainViewModel, MainUiState,
    │                SendStatus, MicrophonePermissionScreen, components/MicButton
    └── navigation   PushToTalkNavHost, MainDestination
```

### Поток данных

```
        нажатие кнопки
              │
              ▼
        MainViewModel ──► StartRecognitionUseCase ──► SpeechRepository ──► SpeechEngine
                                                                              │
                                                          SpeechRecognitionManager
                                                          (единственное место с
                                                           android.speech.SpeechRecognizer)
                                                                              │
                                                     Flow<SpeechEvent>: Preparing →
                                                     ReadyForSpeech → SpeechStarted →
                                                     PartialResult* → SpeechEnded →
                                                     FinalResult | Failed | Cancelled
                                                                              │
                    SpeechRepositoryImpl.scan(...) сворачивает события в RecognitionSession
                                                                              │
        MainViewModel.combine(session, localState) ──► MainUiState ──► MainScreen
                                                                              │
                        FinalResult ──► SendTextUseCase ──► NetworkRepository ──► POST /api/speech
                                                                              │
                                              SendStatus ──► «✅ Отправлено» / «❌ Ошибка отправки»
```

Единственный источник правды о сессии — `StateFlow<RecognitionSession>` в
`SpeechRepositoryImpl`. UI состояние выводится из него и локальных флагов ViewModel
(идёт отправка, разрешение, скрываемая ошибка) и является неизменяемым.

### Работа с SpeechRecognizer

`SpeechRecognitionManager` соблюдает требования платформы:

- все вызовы API распознавателя выполняются в главном потоке (`Dispatchers.Main.immediate`);
- распознаватель используется сессиями, а не для непрерывного слушания;
- ресурсы освобождаются через `destroy()` — `MainViewModel.onCleared()` вызывает
  `CancelRecognitionUseCase` и `ReleaseRecognitionUseCase` в scope приложения;
- собственный VAD не реализуется: начало и конец речи определяет сам движок
  (`onBeginningOfSpeech` / `onEndOfSpeech` плюс extras пауз в `RecognitionConfig`);
- на случай «молчаливых» реализаций `RecognitionService` предусмотрен watchdog,
  закрывающий зависшую сессию по таймауту;
- наружу отдаются только события `SpeechEvent` — callback-ов за пределами data-слоя нет.

Промежуточные результаты (`EXTRA_PARTIAL_RESULTS`) включены, поэтому текст на экране
обновляется в реальном времени ещё до окончания реплики.

### Обработка ошибок

Каждый сценарий сбоя имеет собственный тип в `AppError`:

| Тип | Когда возникает |
|-----|-----------------|
| `Speech.RecognizerUnavailable` | на устройстве нет `RecognitionService` |
| `Speech.MicrophoneUnavailable` | микрофон занят или недоступен (`ERROR_AUDIO`) |
| `Speech.PermissionDenied` | нет `RECORD_AUDIO` |
| `Speech.NoSpeechDetected` | пустая речь, `ERROR_NO_MATCH` |
| `Speech.SpeechTimeout` | пользователь молчал, сработал таймаут |
| `Speech.RecognizerBusy` | предыдущая сессия ещё не завершена |
| `Speech.Cancelled` | сессия отменена |
| `Speech.Client` / `Speech.Server` | ошибки клиента и сервиса распознавания |
| `Speech.Network` / `Speech.NetworkTimeout` | сеть при облачном распознавании |
| `Speech.LanguageUnavailable`, `Speech.TooManyRequests`, `Speech.Unknown` | прочие коды платформы |
| `Network.NoConnection` | нет маршрута, DNS не отвечает, соединение оборвалось |
| `Network.Timeout` | сервер не ответил за отведённое время |
| `Network.Http(code)` | сервер отклонил запрос (4xx) |
| `Network.Server(code)` | сбой на стороне сервера (5xx) |
| `Network.Serialization` | ответ не разобрался: контракт разошёлся с backend-ом |
| `Network.Unexpected` | всё остальное |
| `Validation.EmptyText` | попытка отправить пустой текст |

Перевод в текст для пользователя выполняется в `presentation/main/UiMessages.kt` —
domain остаётся свободным от строковых ресурсов.

## Разрешения

При первом запуске экран запрашивает `RECORD_AUDIO` через Activity Result API. Если разрешения
нет, показывается экран «Нет доступа к микрофону» с кнопками «Разрешить» и «Открыть настройки».
Состояние разрешения перепроверяется на каждом `ON_START`, поэтому возврат из системных настроек
сразу разблокирует основной экран.

## Отправка текста на сервер

Как только `SpeechRecognizer` отдаёт `SpeechEvent.FinalResult`, `MainViewModel` вызывает
`SendTextUseCase`, тот валидирует текст и передаёт его `RetrofitNetworkRepository`:

```
FinalResult ──► SendTextUseCase ──► NetworkRepository ──► POST /api/speech
                     │                                          │
              пустой текст?                              200 / 4xx / 5xx / сбой сети
                     │                                          │
          Validation.EmptyText                       AppResult<Unit> с типизированной ошибкой
                     └──────────────► SendStatus ◄──────────────┘
                                          │
                          «✅ Отправлено» / «❌ Ошибка отправки»
```

Результат живёт в `MainUiState.sendStatus` (`Idle` → `Sending` → `Success`/`Error`), а строки
подбирает `presentation/main/UiMessages.kt` — domain не знает ни про строковые ресурсы, ни про
эмодзи. `MainViewModel` не содержит ни Retrofit, ни `Context`, ни каких-либо Android API.

### Адрес backend-а

Адрес не хранится в коде: он приходит в `BuildConfig.API_BASE_URL` из параметра сборки
`apiBaseUrl` (`gradle.properties`, значение по умолчанию `http://192.168.0.137:8002/`).

```bash
./gradlew assembleDebug -PapiBaseUrl=http://10.0.2.2:8080/    # эмулятор
./gradlew assembleRelease -PreleaseApiBaseUrl=https://ptt.example.com/
```

Сервис работает по HTTP, поэтому нужен и разрешённый cleartext:

- **debug** — `src/debug/res/xml/network_security_config.xml` разрешает HTTP для любого хоста,
  поэтому смена `-PapiBaseUrl` на другой IP работает сразу;
- **release** — `src/main/res/xml/network_security_config.xml` разрешает HTTP только для
  перечисленных адресов, для остальных остаётся требование HTTPS. Новый адрес сервера
  нужно добавить туда, иначе запрос упадёт с `UnknownServiceException`, а на экране это
  неотличимо от обычного «нет соединения с сервером».

### Контракт

| | |
|---|---|
| Запрос | `POST api/speech` c телом `{"text": "..."}` (`SendTextDto`) |
| Успех | `{"status": "ok", "id": 1}` (`SendTextResponseDto`) → `AppResult.Success` |
| 4xx | `Network.Http(code)` |
| 5xx | `Network.Server(code)` |
| Таймаут / нет сети / битый JSON | `Network.Timeout` / `NoConnection` / `Serialization` |

Полное описание сервера — в [`backend/README.md`](backend/README.md).

### Авторизация

В MVP её нет: сервис доступен только в локальной сети, учётные данные в приложении не хранятся.
Точка расширения готова — `AuthInterceptor` добавит `Authorization: Bearer <token>`, как только
`AuthTokenProvider` начнёт возвращать токен; менять `ApiService`, репозитории и UI не придётся.
Заголовок `Authorization` не попадает в логи даже в debug-сборке.

### Работа без сервера

`FakeNetworkRepository` (логирует текст и имитирует задержку) остаётся в проекте. Чтобы
собрать клиент без backend-а, поменяйте одну строку в `di/RepositoryModule.kt`:

```kotlin
@Binds
@Singleton
abstract fun bindNetworkRepository(impl: FakeNetworkRepository): NetworkRepository
```

Больше ничего менять не нужно: `SendTextUseCase`, `MainViewModel` и UI зависят только от
интерфейса `NetworkRepository`.

## Замена STT-движка

`SpeechEngine` — единственная точка расширения. Чтобы подключить Whisper, Vosk, ML Kit или
OpenAI Realtime:

1. Реализуйте `data/speech/SpeechEngine.kt`, эмитируя те же `SpeechEvent`.
2. Поменяйте привязку в `di/RepositoryModule.kt`:

   ```kotlin
   @Binds
   @Singleton
   abstract fun bindSpeechEngine(impl: WhisperSpeechEngine): SpeechEngine
   ```

`SpeechRepositoryImpl`, use case-ы, ViewModel и UI остаются без изменений.

## Режим «удерживай для разговора»

В `presentation/main/MainScreen.kt` достаточно поменять одно значение:

```kotlin
private val PushToTalkButtonMode = PushToTalkMode.Hold
```

`MicButton` переключится с обычного клика на удержание (`detectTapGestures(onPress = ...)`), а
ViewModel получит те же события `onMicPressStart` / `onMicPressEnd`. Бизнес-логика не меняется.

## Сборка и тесты

```bash
./gradlew testDebugUnitTest      # unit-тесты Android
./gradlew lintDebug              # статический анализ
./gradlew assembleDebug          # сборка APK

cd backend && pytest             # тесты backend-а
```

Ни один тест не требует устройства, сети или ручных действий.

### Android — 81 тест

| Набор | Что проверяет |
|-------|---------------|
| `SendTextUseCaseTest` | успех, пустой текст (запрос не уходит), проброс `Http`/`Server`/`Timeout`/`NoConnection` |
| `RetrofitNetworkRepositoryTest` | боевой стек против `MockWebServer`: 200, 400, 422, 500, 503, таймаут, обрыв соединения, выключенный сервер, битый JSON, формат и путь запроса |
| `NetworkErrorMapperTest` | перевод исключений Retrofit/OkHttp/kotlinx в `AppError.Network` |
| `MainViewModelTest` | «✅ Отправлено», «❌ Ошибка отправки», пустое распознавание, двойное удержание кнопки (`RecognizerBusy`), сброс статуса новой сессией, разрешения |
| `SpeechRepositoryImplTest` | свёртка событий в сессию через `FakeSpeechEngine`: полный цикл речи, таймаут, `MicrophoneUnavailable`, отмена |
| `SpeechErrorMapperTest` | коды `SpeechRecognizer` → `AppError.Speech` |
| `UiMessagesTest` | у каждой ошибки и каждого `SendStatus` есть строка |
| `StartRecognitionUseCaseTest` | разрешение и занятость движка |

Зависимости подменяются фейками из `app/src/test/.../fake/Fakes.kt`.

Отдельно есть `RealBackendIntegrationTest` — боевой сетевой стек приложения против живого
сервера. Без адреса он пропускается, поэтому не мешает обычному прогону:

```bash
./gradlew testDebugUnitTest --tests '*RealBackendIntegrationTest*' \
    -PbackendUrl=http://192.168.0.137:8002/
```

### Backend — 50 тестов, покрытие 100 %

Контракт обоих эндпоинтов, валидация, автосоздание SQLite, порядок истории и сквозной
сценарий. Подробности — в [`backend/README.md`](backend/README.md).

### CI

`.github/workflows/ci.yml` перед merge прогоняет тесты backend-а, unit-тесты Android, lint,
сборку APK и сквозной сценарий «клиент → сервер → SQLite → история» на поднятом backend-е.

## Ограничения MVP

- Авторизации нет: сервис рассчитан на локальную сеть и работает по HTTP. Точка расширения
  под `Authorization: Bearer` уже есть — см. раздел «Авторизация».
- Экран один; Navigation Compose добавлен, чтобы новые экраны не требовали правок `MainActivity`.
- Распознавание может использовать облачный сервис устройства — при отсутствии сети
  включите `RecognitionConfig.preferOffline`, если движок поддерживает оффлайн-модель.
- Backend хранит данные в SQLite и рассчитан на один процесс; для нагрузки понадобится
  вынести хранилище в отдельную СУБД.
