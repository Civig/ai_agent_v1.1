const models = [
  {
    name: "GPT-OSS 20B",
    family: "GPT-OSS",
    category: "Рассуждение",
    deployment: "Частный сервер",
    badgeText: "20B / 128K",
    badgeClass: "tag-blue",
    description:
      "Открытая reasoning-модель OpenAI для локального запуска в своей инфраструктуре. Подходит для приватных корпоративных сценариев без зависимости от внешнего облачного API.",
    serverRequirements: [
      "Режим развёртывания: self-hosted / self-managed",
      "Размер модели в Ollama: 14GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Точный порог по GPU/VRAM зависит от backend и квантования"
    ],
    installName: "gpt-oss:20b",
    installCommand: "ollama run gpt-oss:20b",
    officialUrl: "https://help.openai.com/en/articles/11870455-openai-open-weight-models-gpt-oss",
    ollamaUrl: "https://ollama.com/library/gpt-oss:20b",
    sourceLabel: "Источник: OpenAI + Ollama",
    chips: ["open-weight", "reasoning", "128K", "self-hosted"],
    note: "Хороший вариант, если нужен локальный GPT-класс без внешнего облачного API.",
    recommendedFor: ["Продакшн", "Аналитика"]
  },
  {
    name: "GPT-OSS 120B",
    family: "GPT-OSS",
    category: "Рассуждение",
    deployment: "Изолированный контур",
    badgeText: "120B / 128K",
    badgeClass: "tag-blue",
    description:
      "Старшая открытая reasoning-модель OpenAI для мощного on-prem deployment и приватной инфраструктуры.",
    serverRequirements: [
      "Режим развёртывания: self-hosted / self-managed",
      "Размер модели в Ollama: 65GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Нужен выделенный сервер с большим запасом памяти"
    ],
    installName: "gpt-oss:120b",
    installCommand: "ollama run gpt-oss:120b",
    officialUrl: "https://help.openai.com/en/articles/11870455-openai-open-weight-models-gpt-oss",
    ollamaUrl: "https://ollama.com/library/gpt-oss:120b",
    sourceLabel: "Источник: OpenAI + Ollama",
    chips: ["open-weight", "very large", "128K", "private infra"],
    note: "Подходит для тяжёлого локального inference-контура.",
    recommendedFor: ["Продакшн", "Аналитика"]
  },

  {
    name: "Qwen 3.5 0.8B",
    family: "Qwen",
    category: "Мультимодальная",
    deployment: "Локально",
    badgeText: "0.8B / 256K",
    badgeClass: "tag-green",
    description:
      "Компактная мультимодальная модель для текста и изображений. Подходит для пилота, тестового стенда и ограниченных ресурсов.",
    serverRequirements: [
      "Рекомендация по запуску: GPU preferred",
      "Размер модели в Ollama: 1.0GB",
      "Контекстное окно: 256K",
      "Тип входа: текст и изображения",
      "При нехватке памяти рекомендуется уменьшать длину контекста"
    ],
    installName: "qwen3.5:0.8b",
    installCommand: "ollama run qwen3.5:0.8b",
    officialUrl: "https://qwen.readthedocs.io/en/latest/",
    ollamaUrl: "https://ollama.com/library/qwen3.5:0.8b",
    sourceLabel: "Источник: Qwen docs + Ollama",
    chips: ["vision", "пилот", "256K", "компактная"],
    note: "Хороший старт для very-light стенда и демонстрации.",
    recommendedFor: ["Пилот", "Мультимодальность"]
  },
  {
    name: "Qwen 3.5 4B",
    family: "Qwen",
    category: "Мультимодальная",
    deployment: "Локально",
    badgeText: "4B / 256K",
    badgeClass: "tag-amber",
    description:
      "Сбалансированная мультимодальная модель для документов, чата и визуальных внутренних сценариев.",
    serverRequirements: [
      "Рекомендация по запуску: GPU preferred",
      "Размер модели в Ollama: 3.4GB",
      "Контекстное окно: 256K",
      "Тип входа: текст и изображения",
      "Подходит для локальной рабочей станции или тестового сервера"
    ],
    installName: "qwen3.5:4b",
    installCommand: "ollama run qwen3.5:4b",
    officialUrl: "https://qwen.readthedocs.io/en/latest/",
    ollamaUrl: "https://ollama.com/library/qwen3.5:4b",
    sourceLabel: "Источник: Qwen docs + Ollama",
    chips: ["vision", "документы", "256K", "локально"],
    note: "Хороший компромисс между размером и возможностями.",
    recommendedFor: ["Пилот", "Мультимодальность"]
  },
  {
    name: "Qwen 3.5 9B",
    family: "Qwen",
    category: "Мультимодальная",
    deployment: "Частный сервер",
    badgeText: "9B / 256K",
    badgeClass: "tag-amber",
    description:
      "Сильная мультимодальная модель для внутренних ассистентов, анализа документов, скриншотов и интерфейсов.",
    serverRequirements: [
      "Рекомендация по запуску: GPU preferred",
      "Размер модели в Ollama: 6.6GB",
      "Контекстное окно: 256K",
      "Тип входа: текст и изображения",
      "Для длинного контекста нужен запас памяти"
    ],
    installName: "qwen3.5:9b",
    installCommand: "ollama run qwen3.5:9b",
    officialUrl: "https://qwen.readthedocs.io/en/latest/inference/transformers.html",
    ollamaUrl: "https://ollama.com/library/qwen3.5",
    sourceLabel: "Источник: Qwen docs + Ollama",
    chips: ["vision", "9B", "256K", "assistant"],
    note: "Один из самых удачных вариантов для корпоративного локального ассистента.",
    recommendedFor: ["Продакшн", "Мультимодальность"]
  },
  {
    name: "Qwen 3.5 27B",
    family: "Qwen",
    category: "Мультимодальная",
    deployment: "Изолированный контур",
    badgeText: "27B / 256K",
    badgeClass: "tag-blue",
    description:
      "Тяжёлая мультимодальная модель Qwen для серьёзных on-prem сценариев и более высокого качества ответа.",
    serverRequirements: [
      "Рекомендация по запуску: выделенный GPU-сервер",
      "Размер модели в Ollama: 17GB",
      "Контекстное окно: 256K",
      "Тип входа: текст и изображения",
      "Длинный контекст требует существенного запаса памяти"
    ],
    installName: "qwen3.5:27b",
    installCommand: "ollama run qwen3.5:27b",
    officialUrl: "https://qwen.readthedocs.io/en/latest/",
    ollamaUrl: "https://ollama.com/library/qwen3.5",
    sourceLabel: "Источник: Qwen docs + Ollama",
    chips: ["27B", "vision", "256K", "heavy"],
    note: "Уже уровень выделенного локального inference-сервера.",
    recommendedFor: ["Продакшн", "Мультимодальность"]
  },

  {
    name: "Qwen3-Coder 30B",
    family: "Qwen",
    category: "Код",
    deployment: "Изолированный контур",
    badgeText: "30B / 256K",
    badgeClass: "tag-blue",
    description:
      "Специализированная coding-модель для agentic coding, репозиториев и длинного контекста.",
    serverRequirements: [
      "Режим запуска: локальный inference",
      "Размер модели в Ollama: 19GB",
      "Контекстное окно: 256K",
      "Тип входа: текст",
      "Подходит для выделенного coding-сервера"
    ],
    installName: "qwen3-coder:30b",
    installCommand: "ollama run qwen3-coder:30b",
    officialUrl: "https://qwenlm.github.io/blog/qwen3-coder/",
    ollamaUrl: "https://ollama.com/library/qwen3-coder:30b",
    sourceLabel: "Источник: Qwen3-Coder + Ollama",
    chips: ["coding", "agentic", "256K", "repo-scale"],
    note: "Сильный вариант для внутреннего dev-ассистента.",
    recommendedFor: ["Код", "Продакшн"]
  },
  {
    name: "Qwen3-Coder 480B",
    family: "Qwen",
    category: "Код",
    deployment: "Изолированный контур",
    badgeText: "480B / 256K",
    badgeClass: "tag-blue",
    description:
      "Старшая coding-модель для тяжёлых agentic и repository-scale сценариев.",
    serverRequirements: [
      "Ориентир по локальному запуску: минимум 250GB памяти или unified memory",
      "Размер модели в Ollama: 290GB",
      "Контекстное окно: 256K",
      "Тип входа: текст",
      "Требует очень мощную инфраструктуру"
    ],
    installName: "qwen3-coder:480b",
    installCommand: "ollama run qwen3-coder:480b",
    officialUrl: "https://ollama.com/library/qwen3-coder",
    ollamaUrl: "https://ollama.com/library/qwen3-coder:480b",
    sourceLabel: "Источник: Ollama",
    chips: ["coding", "480B", "256K", "very large"],
    note: "Это уже не пилот, а тяжёлый локальный coding-контур.",
    recommendedFor: ["Код"]
  },

  {
    name: "Qwen2.5-Coder 0.5B",
    family: "Qwen",
    category: "Код",
    deployment: "Локально",
    badgeText: "0.5B / 32K",
    badgeClass: "tag-green",
    description:
      "Очень компактная coding-модель для лёгкого пилота, быстрых тестов и простых задач разработки.",
    serverRequirements: [
      "Размер модели в Ollama: 398MB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для минимального локального стенда",
      "Используется как very-light coding baseline"
    ],
    installName: "qwen2.5-coder:0.5b",
    installCommand: "ollama run qwen2.5-coder:0.5b",
    officialUrl: "https://ollama.com/library/qwen2.5-coder",
    ollamaUrl: "https://ollama.com/library/qwen2.5-coder:0.5b",
    sourceLabel: "Источник: Ollama",
    chips: ["coding", "0.5B", "32K", "compact"],
    note: "Минимальный вход в локальный coding-контур.",
    recommendedFor: ["Пилот", "Код"]
  },
  {
    name: "Qwen2.5-Coder 7B",
    family: "Qwen",
    category: "Код",
    deployment: "Локально",
    badgeText: "7B / 32K",
    badgeClass: "tag-amber",
    description:
      "Сбалансированная coding-модель для локального IDE-ассистента и внутренних инженерных задач.",
    serverRequirements: [
      "Размер модели в Ollama: 4.7GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для локальной рабочей станции или небольшого сервера",
      "Умеренные требования по ресурсам"
    ],
    installName: "qwen2.5-coder:7b",
    installCommand: "ollama run qwen2.5-coder:7b",
    officialUrl: "https://ollama.com/library/qwen2.5-coder",
    ollamaUrl: "https://ollama.com/library/qwen2.5-coder:7b",
    sourceLabel: "Источник: Ollama",
    chips: ["coding", "7B", "32K", "local dev"],
    note: "Хороший middle-range вариант для локальной разработки.",
    recommendedFor: ["Код", "Пилот"]
  },
  {
    name: "Qwen2.5-Coder 14B Instruct",
    family: "Qwen",
    category: "Код",
    deployment: "Частный сервер",
    badgeText: "14B / 32K",
    badgeClass: "tag-blue",
    description:
      "Более сильная coding-модель для внутренних dev-сервисов, code review и генерации кода.",
    serverRequirements: [
      "Размер модели в Ollama: 9.0GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для выделенного coding-сервера",
      "Лучше использовать при постоянной инженерной нагрузке"
    ],
    installName: "qwen2.5-coder:14b-instruct",
    installCommand: "ollama run qwen2.5-coder:14b-instruct",
    officialUrl: "https://ollama.com/library/qwen2.5-coder",
    ollamaUrl: "https://ollama.com/library/qwen2.5-coder",
    sourceLabel: "Источник: Ollama",
    chips: ["coding", "14B", "32K", "instruct"],
    note: "Уже production-класс для локального coding-assistant.",
    recommendedFor: ["Код", "Продакшн"]
  },
  {
    name: "Qwen2.5-Coder 32B Instruct",
    family: "Qwen",
    category: "Код",
    deployment: "Изолированный контур",
    badgeText: "32B / 32K",
    badgeClass: "tag-blue",
    description:
      "Тяжёлая локальная coding-модель для случаев, когда нужен заметный запас по качеству.",
    serverRequirements: [
      "Размер модели в Ollama: 20GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Нужен серьёзный запас памяти",
      "Подходит для выделенного локального dev-контура"
    ],
    installName: "qwen2.5-coder:32b-instruct",
    installCommand: "ollama run qwen2.5-coder:32b-instruct",
    officialUrl: "https://ollama.com/library/qwen2.5-coder",
    ollamaUrl: "https://ollama.com/library/qwen2.5-coder",
    sourceLabel: "Источник: Ollama",
    chips: ["coding", "32B", "32K", "heavy"],
    note: "Для выделенного on-prem coding-контура.",
    recommendedFor: ["Код", "Продакшн"]
  },

  {
    name: "Llama 3.1 8B",
    family: "Llama",
    category: "Чат",
    deployment: "Локально",
    badgeText: "8B / 128K",
    badgeClass: "tag-cyan",
    description:
      "Надёжная текстовая модель для корпоративного чата, поиска по знаниям, RAG и внутренних помощников.",
    serverRequirements: [
      "Ориентир Meta для fp16: GPU с 16GB VRAM",
      "Размер модели в Ollama: 4.9GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Квантованные версии снижают требования к памяти"
    ],
    installName: "llama3.1:8b",
    installCommand: "ollama run llama3.1:8b",
    officialUrl: "https://www.llama.com/docs/llama-everywhere/running-meta-llama-on-linux/",
    ollamaUrl: "https://ollama.com/library/llama3.1:8b",
    sourceLabel: "Источник: Meta Llama + Ollama",
    chips: ["chat", "RAG", "128K", "8B"],
    note: "Один из лучших вариантов для старта локального корпоративного ассистента.",
    recommendedFor: ["Пилот", "Продакшн"]
  },
  {
    name: "Llama 3.1 70B",
    family: "Llama",
    category: "Чат",
    deployment: "Изолированный контур",
    badgeText: "70B / 128K",
    badgeClass: "tag-blue",
    description:
      "Тяжёлая Llama 3.1 для более серьёзных self-hosted сценариев и высокого качества ответа.",
    serverRequirements: [
      "Ориентир Meta для fp16: около 140GB VRAM",
      "Размер модели в Ollama: 43GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Требуется very-high-end инфраструктура"
    ],
    installName: "llama3.1:70b",
    installCommand: "ollama run llama3.1:70b",
    officialUrl: "https://www.llama.com/models/llama-3/",
    ollamaUrl: "https://ollama.com/library/llama3.1:70b",
    sourceLabel: "Источник: Meta Llama + Ollama",
    chips: ["70B", "128K", "large", "on-prem"],
    note: "Подходит не для пилота, а для тяжёлого локального inference.",
    recommendedFor: ["Продакшн"]
  },
  {
    name: "Llama 3.1 405B",
    family: "Llama",
    category: "Чат",
    deployment: "Изолированный контур",
    badgeText: "405B / 128K",
    badgeClass: "tag-blue",
    description:
      "Старшая Llama 3.1 с очень крупным весом артефакта и инфраструктурными требованиями enterprise-уровня.",
    serverRequirements: [
      "Размер модели в Ollama: 243GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Требует проектирования инфраструктуры как отдельной задачи",
      "Это very-large self-hosted deployment"
    ],
    installName: "llama3.1:405b",
    installCommand: "ollama run llama3.1:405b",
    officialUrl: "https://www.llama.com/models/llama-3/",
    ollamaUrl: "https://ollama.com/library/llama3.1:405b",
    sourceLabel: "Источник: Meta Llama + Ollama",
    chips: ["405B", "128K", "very large", "server class"],
    note: "Карточка скорее как ориентир масштаба, чем как обычный стендовый выбор.",
    recommendedFor: ["Продакшн"]
  },

  {
    name: "Gemma 3 270M",
    family: "Gemma",
    category: "Чат",
    deployment: "Локально",
    badgeText: "270M / 32K",
    badgeClass: "tag-green",
    description:
      "Самый лёгкий Gemma 3-вариант для очень компактных локальных сценариев и тестов.",
    serverRequirements: [
      "Семейство Gemma 3 ориентировано на single GPU/TPU",
      "Размер модели в Ollama: 292MB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для very-light локального стенда"
    ],
    installName: "gemma3:270m",
    installCommand: "ollama run gemma3:270m",
    officialUrl: "https://deepmind.google/models/gemma/gemma-3/",
    ollamaUrl: "https://ollama.com/library/gemma3:270m",
    sourceLabel: "Источник: Google Gemma + Ollama",
    chips: ["270M", "32K", "compact", "single GPU"],
    note: "Максимально лёгкий вариант в семействе Gemma.",
    recommendedFor: ["Пилот"]
  },
  {
    name: "Gemma 3 4B",
    family: "Gemma",
    category: "Мультимодальная",
    deployment: "Локально",
    badgeText: "4B / 128K",
    badgeClass: "tag-green",
    description:
      "Компактная мультимодальная Gemma 3 для текста, документов и изображений.",
    serverRequirements: [
      "Ориентир по весам int4: около 2.6GB VRAM только под веса",
      "Размер модели в Ollama: 3.3GB",
      "Контекстное окно: 128K",
      "Тип входа: текст и изображения",
      "Подходит для умеренного локального сервера"
    ],
    installName: "gemma3:4b",
    installCommand: "ollama run gemma3:4b",
    officialUrl: "https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/",
    ollamaUrl: "https://ollama.com/library/gemma3:4b",
    sourceLabel: "Источник: Google Gemma + Ollama",
    chips: ["vision", "4B", "128K", "compact"],
    note: "Удобный мультимодальный вариант под умеренные ресурсы.",
    recommendedFor: ["Пилот", "Мультимодальность"]
  },
  {
    name: "Gemma 3 12B",
    family: "Gemma",
    category: "Мультимодальная",
    deployment: "Частный сервер",
    badgeText: "12B / 128K",
    badgeClass: "tag-amber",
    description:
      "Сильная мультимодальная Gemma 3 для документов, изображений и внутренних AI-сервисов.",
    serverRequirements: [
      "Ориентир Google для Gemma 3 12B int4: RTX 4060 Laptop GPU с 8GB VRAM",
      "Вес int4: около 6.6GB VRAM только под веса",
      "Размер модели в Ollama: 8.1GB",
      "Контекстное окно: 128K",
      "Тип входа: текст и изображения"
    ],
    installName: "gemma3:12b",
    installCommand: "ollama run gemma3:12b",
    officialUrl: "https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/",
    ollamaUrl: "https://ollama.com/library/gemma3:12b",
    sourceLabel: "Источник: Google Gemma + Ollama",
    chips: ["vision", "12B", "8GB VRAM", "128K"],
    note: "Сильный компромисс между качеством и требованиями к GPU.",
    recommendedFor: ["Продакшн", "Мультимодальность"]
  },
  {
    name: "Gemma 3 27B",
    family: "Gemma",
    category: "Мультимодальная",
    deployment: "Изолированный контур",
    badgeText: "27B / 128K",
    badgeClass: "tag-blue",
    description:
      "Старшая мультимодальная Gemma 3 для тяжёлых on-prem сценариев.",
    serverRequirements: [
      "Ориентир Google для Gemma 3 27B int4: NVIDIA RTX 3090 с 24GB VRAM",
      "Вес int4: около 14.1GB VRAM только под веса",
      "Размер модели в Ollama: 17GB",
      "Контекстное окно: 128K",
      "Тип входа: текст и изображения"
    ],
    installName: "gemma3:27b",
    installCommand: "ollama run gemma3:27b",
    officialUrl: "https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/",
    ollamaUrl: "https://ollama.com/library/gemma3:27b",
    sourceLabel: "Источник: Google Gemma + Ollama",
    chips: ["vision", "27B", "24GB VRAM", "128K"],
    note: "Серьёзный мультимодальный on-prem вариант.",
    recommendedFor: ["Продакшн", "Мультимодальность"]
  },

  {
    name: "Phi-4 Mini",
    family: "Phi",
    category: "Чат",
    deployment: "Локально",
    badgeText: "3.8B / 128K",
    badgeClass: "tag-green",
    description:
      "Лёгкая модель семейства Phi-4 для multilingual, reasoning-dense и function-calling сценариев.",
    serverRequirements: [
      "Требуется Ollama 0.5.13+",
      "Для Foundry Local: минимум 8GB RAM и 3GB диска, рекомендовано 16GB RAM и 15GB диска",
      "Размер модели в Ollama: 2.5GB",
      "Контекстное окно: 128K",
      "Тип входа: текст"
    ],
    installName: "phi4-mini",
    installCommand: "ollama run phi4-mini",
    officialUrl: "https://learn.microsoft.com/en-us/azure/foundry-local/get-started",
    ollamaUrl: "https://ollama.com/library/phi4-mini",
    sourceLabel: "Источник: Microsoft + Ollama",
    chips: ["3.8B", "128K", "compact", "function calling"],
    note: "Очень удобный вариант для пилота и небольших корпоративных сервисов.",
    recommendedFor: ["Пилот"]
  },
  {
    name: "Phi-4 Mini Reasoning",
    family: "Phi",
    category: "Рассуждение",
    deployment: "Локально",
    badgeText: "3.8B / 128K",
    badgeClass: "tag-green",
    description:
      "Лёгкая reasoning-модель Phi для логики, математики и constrained environments.",
    serverRequirements: [
      "Если использовать Foundry Local: минимум 8GB RAM и 3GB диска, рекомендовано 16GB RAM и 15GB диска",
      "Размер модели в Ollama: 3.2GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Подходит для memory-constrained локального стенда"
    ],
    installName: "phi4-mini-reasoning",
    installCommand: "ollama run phi4-mini-reasoning",
    officialUrl: "https://ollama.com/library/phi4-mini-reasoning",
    ollamaUrl: "https://ollama.com/library/phi4-mini-reasoning",
    sourceLabel: "Источник: Microsoft + Ollama",
    chips: ["reasoning", "3.8B", "128K", "compact"],
    note: "Один из лучших лёгких reasoning-вариантов.",
    recommendedFor: ["Пилот", "Аналитика"]
  },
  {
    name: "Phi-4",
    family: "Phi",
    category: "Рассуждение",
    deployment: "Частный сервер",
    badgeText: "14B / 16K",
    badgeClass: "tag-blue",
    description:
      "14B open model от Microsoft для reasoning, аналитики и внутренних текстовых сервисов.",
    serverRequirements: [
      "Для Foundry Local: минимум 8GB RAM и 3GB диска, рекомендовано 16GB RAM и 15GB диска",
      "Размер модели в Ollama: 9.1GB",
      "Контекстное окно: 16K",
      "Тип входа: текст",
      "Ориентирована на low-latency локальный inference"
    ],
    installName: "phi4",
    installCommand: "ollama run phi4",
    officialUrl: "https://azure.microsoft.com/en-us/products/phi",
    ollamaUrl: "https://ollama.com/library/phi4",
    sourceLabel: "Источник: Microsoft + Ollama",
    chips: ["14B", "16K", "reasoning", "low latency"],
    note: "Сильный локальный reasoning-вариант без экстремальных требований.",
    recommendedFor: ["Продакшн", "Аналитика"]
  },
  {
    name: "Phi-4 Reasoning",
    family: "Phi",
    category: "Рассуждение",
    deployment: "Частный сервер",
    badgeText: "14B / 32K",
    badgeClass: "tag-blue",
    description:
      "Open-weight reasoning-модель Phi для сложных логических и аналитических задач.",
    serverRequirements: [
      "Размер модели в Ollama: 11GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Базовые требования Foundry Local: 8GB RAM минимум / 16GB рекомендовано",
      "Подходит для локального reasoning-контра"
    ],
    installName: "phi4-reasoning",
    installCommand: "ollama run phi4-reasoning",
    officialUrl: "https://ollama.com/library/phi4-reasoning",
    ollamaUrl: "https://ollama.com/library/phi4-reasoning",
    sourceLabel: "Источник: Microsoft + Ollama",
    chips: ["14B", "32K", "reasoning", "open-weight"],
    note: "Подходит для внутренних аналитических задач и логики.",
    recommendedFor: ["Продакшн", "Аналитика"]
  },

  {
    name: "DeepSeek-R1 1.5B",
    family: "DeepSeek",
    category: "Рассуждение",
    deployment: "Локально",
    badgeText: "1.5B / 128K",
    badgeClass: "tag-green",
    description:
      "Компактный distilled reasoning-вариант для лёгкого локального стенда.",
    serverRequirements: [
      "Размер модели в Ollama: 1.1GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Подходит для very-light reasoning-пилота",
      "Требования зависят от выбранного backend и квантования"
    ],
    installName: "deepseek-r1:1.5b",
    installCommand: "ollama run deepseek-r1:1.5b",
    officialUrl: "https://github.com/deepseek-ai/DeepSeek-R1",
    ollamaUrl: "https://ollama.com/library/deepseek-r1:1.5b",
    sourceLabel: "Источник: DeepSeek + Ollama",
    chips: ["reasoning", "1.5B", "128K", "compact"],
    note: "Минимальный вход в reasoning-семейство DeepSeek-R1.",
    recommendedFor: ["Пилот", "Аналитика"]
  },
  {
    name: "DeepSeek-R1 8B",
    family: "DeepSeek",
    category: "Рассуждение",
    deployment: "Частный сервер",
    badgeText: "8B / 128K",
    badgeClass: "tag-amber",
    description:
      "Популярный локальный reasoning-вариант для математики, логики и аналитики.",
    serverRequirements: [
      "Размер модели в Ollama: 5.2GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Точный minimum по VRAM зависит от квантования и backend",
      "Подходит для on-prem reasoning-задач"
    ],
    installName: "deepseek-r1:8b",
    installCommand: "ollama run deepseek-r1:8b",
    officialUrl: "https://github.com/deepseek-ai/DeepSeek-R1",
    ollamaUrl: "https://ollama.com/library/deepseek-r1:8b",
    sourceLabel: "Источник: DeepSeek + Ollama",
    chips: ["reasoning", "8B", "128K", "math"],
    note: "Практичный on-prem вариант для reasoning-кейсов.",
    recommendedFor: ["Аналитика", "Продакшн"]
  },
  {
    name: "DeepSeek-R1 32B",
    family: "DeepSeek",
    category: "Рассуждение",
    deployment: "Изолированный контур",
    badgeText: "32B / 128K",
    badgeClass: "tag-blue",
    description:
      "Тяжёлая reasoning-модель для более серьёзных on-prem сценариев.",
    serverRequirements: [
      "Размер модели в Ollama: 20GB",
      "Контекстное окно: 128K",
      "Тип входа: текст",
      "Класс выделенного сервера",
      "Нужен существенный запас памяти"
    ],
    installName: "deepseek-r1:32b",
    installCommand: "ollama run deepseek-r1:32b",
    officialUrl: "https://github.com/deepseek-ai/DeepSeek-R1",
    ollamaUrl: "https://ollama.com/library/deepseek-r1:32b",
    sourceLabel: "Источник: DeepSeek + Ollama",
    chips: ["reasoning", "32B", "128K", "heavy"],
    note: "Для сценариев, где 8B уже недостаточно.",
    recommendedFor: ["Продакшн", "Аналитика"]
  },

  {
    name: "DeepSeek-Coder 1.3B",
    family: "DeepSeek",
    category: "Код",
    deployment: "Локально",
    badgeText: "1.3B / 16K",
    badgeClass: "tag-green",
    description:
      "Лёгкая coding-модель для локального пилота и простых инженерных задач.",
    serverRequirements: [
      "Размер модели в Ollama: 776MB",
      "Контекстное окно: 16K",
      "Тип входа: текст",
      "Подходит для very-light coding-стенда",
      "Ориентирована на code generation и code completion"
    ],
    installName: "deepseek-coder:1.3b",
    installCommand: "ollama run deepseek-coder:1.3b",
    officialUrl: "https://ollama.com/library/deepseek-coder",
    ollamaUrl: "https://ollama.com/library/deepseek-coder:1.3b",
    sourceLabel: "Источник: DeepSeek-Coder + Ollama",
    chips: ["coding", "1.3B", "16K", "compact"],
    note: "Минимальный вход в DeepSeek coding-линейку.",
    recommendedFor: ["Пилот", "Код"]
  },
  {
    name: "DeepSeek-Coder 33B",
    family: "DeepSeek",
    category: "Код",
    deployment: "Изолированный контур",
    badgeText: "33B / 16K",
    badgeClass: "tag-blue",
    description:
      "Старший coding-вариант для локального dev-контура и тяжёлых инженерных задач.",
    serverRequirements: [
      "Размер модели в Ollama: 19GB",
      "Контекстное окно: 16K",
      "Тип входа: текст",
      "Нужен выделенный coding-сервер",
      "Подходит для серьёзной внутренней разработки"
    ],
    installName: "deepseek-coder:33b",
    installCommand: "ollama run deepseek-coder:33b",
    officialUrl: "https://ollama.com/library/deepseek-coder",
    ollamaUrl: "https://ollama.com/library/deepseek-coder:33b",
    sourceLabel: "Источник: DeepSeek-Coder + Ollama",
    chips: ["coding", "33B", "16K", "heavy"],
    note: "Хорош для выделенного локального coding-сервера.",
    recommendedFor: ["Код", "Продакшн"]
  },
  {
    name: "DeepSeek-Coder-V2 16B",
    family: "DeepSeek",
    category: "Код",
    deployment: "Частный сервер",
    badgeText: "16B / 160K",
    badgeClass: "tag-amber",
    description:
      "MoE coding-модель с большим контекстом для сложных coding-сессий и длинных задач.",
    serverRequirements: [
      "Размер модели в Ollama: 8.9GB",
      "Контекстное окно: 160K",
      "Тип входа: текст",
      "Подходит для coding-задач с длинным контекстом",
      "Хороша для внутреннего dev-ассистента"
    ],
    installName: "deepseek-coder-v2:16b",
    installCommand: "ollama run deepseek-coder-v2:16b",
    officialUrl: "https://ollama.com/library/deepseek-coder-v2",
    ollamaUrl: "https://ollama.com/library/deepseek-coder-v2:16b",
    sourceLabel: "Источник: DeepSeek-Coder-V2 + Ollama",
    chips: ["coding", "16B", "160K", "MoE"],
    note: "Сильный вариант под длинные coding-сессии.",
    recommendedFor: ["Код", "Продакшн"]
  },

  {
    name: "Mistral 7B",
    family: "Mistral",
    category: "Чат",
    deployment: "Локально",
    badgeText: "7B / 32K",
    badgeClass: "tag-green",
    description:
      "Классический компактный Mistral для текста и локального чата.",
    serverRequirements: [
      "Размер модели в Ollama: 4.4GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для лёгкого локального сервера",
      "Хороший базовый текстовый вариант"
    ],
    installName: "mistral",
    installCommand: "ollama run mistral",
    officialUrl: "https://ollama.com/library/mistral",
    ollamaUrl: "https://ollama.com/library/mistral",
    sourceLabel: "Источник: Mistral + Ollama",
    chips: ["chat", "7B", "32K", "light"],
    note: "Хорошая базовая текстовая модель без тяжёлых требований.",
    recommendedFor: ["Пилот"]
  },
  {
    name: "Mistral Small 3 24B",
    family: "Mistral",
    category: "Чат",
    deployment: "Частный сервер",
    badgeText: "24B / 32K",
    badgeClass: "tag-amber",
    description:
      "Mistral Small 3 для быстрого локального чата и knowledge-dense сценариев.",
    serverRequirements: [
      "Ориентир по железу: одна RTX 4090 или MacBook с 32GB RAM после квантования",
      "Размер модели в Ollama: 14GB",
      "Контекстное окно: 32K",
      "Тип входа: текст",
      "Подходит для fast-response conversational agents"
    ],
    installName: "mistral-small",
    installCommand: "ollama run mistral-small",
    officialUrl: "https://ollama.com/library/mistral-small",
    ollamaUrl: "https://ollama.com/library/mistral-small",
    sourceLabel: "Источник: Mistral + Ollama",
    chips: ["24B", "RTX 4090", "32K", "chat"],
    note: "Один из самых понятных по железу on-prem вариантов.",
    recommendedFor: ["Продакшн"]
  },
  {
    name: "Mistral Small 3.1 24B",
    family: "Mistral",
    category: "Мультимодальная",
    deployment: "Частный сервер",
    badgeText: "24B / 128K",
    badgeClass: "tag-amber",
    description:
      "Мультимодальная версия Mistral Small с текстом, изображениями и длинным контекстом.",
    serverRequirements: [
      "Требуется Ollama 0.6.5 или выше",
      "Размер модели в Ollama: 15GB",
      "Контекстное окно: 128K",
      "Тип входа: текст и изображения",
      "Для q8_0-варианта размер артефакта: 26GB"
    ],
    installName: "mistral-small3.1:24b",
    installCommand: "ollama run mistral-small3.1:24b",
    officialUrl: "https://ollama.com/library/mistral-small3.1",
    ollamaUrl: "https://ollama.com/library/mistral-small3.1:24b",
    sourceLabel: "Источник: Mistral + Ollama",
    chips: ["vision", "24B", "128K", "Ollama 0.6.5+"],
    note: "Хороший мультимодальный on-prem вариант на одном сильном сервере.",
    recommendedFor: ["Мультимодальность", "Продакшн"]
  },
  {
    name: "Mistral Nemo 12B",
    family: "Mistral",
    category: "Чат",
    deployment: "Частный сервер",
    badgeText: "12B / 1000K",
    badgeClass: "tag-blue",
    description:
      "12B-модель Mistral с очень длинным контекстом для задач, где критичен большой контекстный буфер.",
    serverRequirements: [
      "Размер модели в Ollama: 7.1GB",
      "Контекстное окно: 1000K",
      "Тип входа: текст",
      "Подходит для задач с очень длинным контекстом",
      "Требует аккуратного контроля памяти на длинных запросах"
    ],
    installName: "mistral-nemo",
    installCommand: "ollama run mistral-nemo",
    officialUrl: "https://ollama.com/library/mistral-nemo",
    ollamaUrl: "https://ollama.com/library/mistral-nemo",
    sourceLabel: "Источник: Mistral + Ollama",
    chips: ["12B", "1000K", "long context", "text"],
    note: "Сильный выбор, если важен очень длинный контекст.",
    recommendedFor: ["Продакшн", "Аналитика"]
  }
];

const QUICK_PRESETS = {
  pilot: {
    label: "Для пилота",
    title: "Рекомендованные модели для пилота",
    filter: (model) =>
      model.recommendedFor.includes("Пилот") ||
      model.deployment === "Локально"
  },
  production: {
    label: "Для production",
    title: "Рекомендованные модели для production",
    filter: (model) => model.recommendedFor.includes("Продакшн")
  },
  coding: {
    label: "Для кода",
    title: "Рекомендованные модели для coding-сценариев",
    filter: (model) =>
      model.recommendedFor.includes("Код") || model.category === "Код"
  },
  multimodal: {
    label: "Мультимодальные",
    title: "Рекомендованные мультимодальные модели",
    filter: (model) =>
      model.recommendedFor.includes("Мультимодальность") ||
      model.category === "Мультимодальная"
  },
  analytics: {
    label: "Для аналитики",
    title: "Рекомендованные модели для reasoning и аналитики",
    filter: (model) =>
      model.recommendedFor.includes("Аналитика") ||
      model.category === "Рассуждение"
  }
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function createRequirementsHtml(items) {
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function createChipsHtml(chips) {
  return chips
    .map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`)
    .join("");
}

function createLinksHtml(model) {
  return `
    <div class="card-links">
      <a class="link-btn" href="${escapeHtml(model.officialUrl)}" target="_blank" rel="noopener noreferrer">
        Официальная страница
      </a>
      <a class="link-btn link-btn-secondary" href="${escapeHtml(model.ollamaUrl)}" target="_blank" rel="noopener noreferrer">
        Страница модели в Ollama
      </a>
    </div>
  `;
}

function createModelCard(model) {
  return `
    <article class="model-card">
      <div class="model-top">
        <div>
          <h3>${escapeHtml(model.name)}</h3>
          <div class="model-provider">Семейство ${escapeHtml(model.family)}</div>
        </div>
        <span class="tag ${escapeHtml(model.badgeClass)}">${escapeHtml(model.badgeText)}</span>
      </div>

      <div class="requirements-box">
        <div class="requirements-title">Требования и характеристики</div>
        <ul class="requirements-list">
          ${createRequirementsHtml(model.serverRequirements)}
        </ul>
      </div>

      <div class="install-box">
        <div class="install-label">Имя модели для установки</div>
        <code class="install-command">${escapeHtml(model.installName)}</code>
      </div>

      <div class="install-box">
        <div class="install-label">Команда запуска через Ollama</div>
        <code class="install-command">${escapeHtml(model.installCommand)}</code>
      </div>

      <div class="model-desc">
        ${escapeHtml(model.description)}
      </div>

      <div class="chips">
        ${createChipsHtml(model.chips)}
      </div>

      ${createLinksHtml(model)}

      <div class="model-footer">
        <div class="model-note">
          ${escapeHtml(model.sourceLabel)}<br />
          ${escapeHtml(model.note)}
        </div>
        <span class="tag tag-cyan">${escapeHtml(model.installName)}</span>
      </div>
    </article>
  `;
}

function normalizeValue(value) {
  return String(value || "").trim().toLowerCase();
}

function getControls() {
  return {
    searchInput: document.getElementById("search"),
    familySelect: document.getElementById("provider"),
    categorySelect: document.getElementById("category"),
    deploymentSelect: document.getElementById("deployment")
  };
}

function filterModels() {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  const searchValue = normalizeValue(searchInput?.value);
  const familyValue = familySelect?.value || "Все семейства";
  const categoryValue = categorySelect?.value || "Все категории";
  const deploymentValue = deploymentSelect?.value || "Все варианты";

  return models.filter((model) => {
    const haystack = [
      model.name,
      model.family,
      model.description,
      model.installName,
      model.installCommand,
      model.sourceLabel,
      model.note,
      ...model.serverRequirements,
      ...model.chips,
      ...model.recommendedFor
    ]
      .join(" ")
      .toLowerCase();

    const matchesSearch = !searchValue || haystack.includes(searchValue);
    const matchesFamily =
      familyValue === "Все семейства" || model.family === familyValue;
    const matchesCategory =
      categoryValue === "Все категории" || model.category === categoryValue;
    const matchesDeployment =
      deploymentValue === "Все варианты" || model.deployment === deploymentValue;

    return (
      matchesSearch && matchesFamily && matchesCategory && matchesDeployment
    );
  });
}

function updateCounters(filteredModels) {
  const resultsCount = document.getElementById("resultsCount");

  if (resultsCount) {
    resultsCount.textContent =
      filteredModels.length === models.length
        ? `Показаны все модели (${filteredModels.length})`
        : `Найдено моделей: ${filteredModels.length}`;
  }
}

function renderModels() {
  const list = document.getElementById("modelsList");
  const emptyState = document.getElementById("emptyState");

  if (!list) return;

  const filteredModels = filterModels();

  if (filteredModels.length === 0) {
    list.innerHTML = "";
    if (emptyState) emptyState.hidden = false;
    updateCounters(filteredModels);
    return;
  }

  if (emptyState) emptyState.hidden = true;
  list.innerHTML = filteredModels.map(createModelCard).join("");
  updateCounters(filteredModels);
}

function clearFilters() {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = "";
  if (familySelect) familySelect.value = "Все семейства";
  if (categorySelect) categorySelect.value = "Все категории";
  if (deploymentSelect) deploymentSelect.value = "Все варианты";

  setActiveQuickFilter(null);
  renderModels();
}

function setActiveQuickFilter(activeButton) {
  const buttons = document.querySelectorAll(".quick-filter");
  buttons.forEach((button) => {
    button.classList.toggle("is-active", button === activeButton);
  });
}

function applyQuickPreset(key) {
  const preset = QUICK_PRESETS[key];
  if (!preset) return;

  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = "";
  if (familySelect) familySelect.value = "Все семейства";
  if (categorySelect) categorySelect.value = "Все категории";
  if (deploymentSelect) deploymentSelect.value = "Все варианты";

  const filtered = models.filter(preset.filter);
  const list = document.getElementById("modelsList");
  const emptyState = document.getElementById("emptyState");

  if (!list) return;

  setActiveQuickFilter(
    document.querySelector(`.quick-filter[data-quick-filter="${key}"]`)
  );

  if (filtered.length === 0) {
    list.innerHTML = "";
    if (emptyState) emptyState.hidden = false;
    updateCounters(filtered);
    return;
  }

  if (emptyState) emptyState.hidden = true;
  list.innerHTML = filtered.map(createModelCard).join("");
  updateCounters(filtered);
}

function applyQuickSelection(button) {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = button.dataset.quickSearch || "";
  if (familySelect) {
    familySelect.value = button.dataset.quickFamily || "Все семейства";
  }
  if (categorySelect) {
    categorySelect.value = button.dataset.quickCategory || "Все категории";
  }
  if (deploymentSelect) {
    deploymentSelect.value = button.dataset.quickDeployment || "Все варианты";
  }

  setActiveQuickFilter(button);
  renderModels();
  document.getElementById("catalog")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initQuickFilters() {
  const buttons = document.querySelectorAll(".quick-filter");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.quickFilter;

      if (key) {
        applyQuickPreset(key);
        return;
      }

      applyQuickSelection(button);
    });
  });

  const resetButton = document.getElementById("resetFilters");
  if (resetButton) {
    resetButton.addEventListener("click", clearFilters);
  }
}

function initControls() {
  const controls = ["search", "provider", "category", "deployment"];

  controls.forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;

    const handler = () => {
      setActiveQuickFilter(null);
      renderModels();
    };

    element.addEventListener("input", handler);
    element.addEventListener("change", handler);
  });
}

function populateProviderSelect() {
  const familySelect = document.getElementById("provider");
  if (!familySelect) return;

  const currentValue = familySelect.value;
  const families = [...new Set(models.map((model) => model.family))].sort();

  familySelect.innerHTML = `
    <option>Все семейства</option>
    ${families
      .map((family) => `<option>${escapeHtml(family)}</option>`)
      .join("")}
  `;

  if (families.includes(currentValue)) {
    familySelect.value = currentValue;
  } else {
    familySelect.value = "Все семейства";
  }
}

function initCatalog() {
  populateProviderSelect();
  initQuickFilters();
  initControls();
  renderModels();
}

document.addEventListener("DOMContentLoaded", initCatalog);
