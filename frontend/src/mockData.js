/** Demo fallback data for OnboardAI. */
export const sampleQuestions = [
  "Give me today's brief",
  "What is Velora's main product?",
  "Who are our main competitors?",
  "What's our tech stack?",
  "How many people are on the team?",
  "What's our pricing strategy?",
  "What integrations do we support?",
  "Who led our seed round?",
  "What's our target market?",
  "What are the Q1 2024 priorities?",
  "How do we compare to Gorgias?",
]

export const mockAnswers = {
  "What is Velora's main product?": {
    answer:
      "Velora builds an AI-powered customer support platform specifically designed for e-commerce businesses. Our product reduces support ticket resolution time by 80% using large language models trained on merchant-specific data.",
    citations: [
      {
        source: "notion",
        title: "Velora Product Strategy 2024",
        snippet: "AI-powered customer support platform for e-commerce. Key features: automated ticket routing, sentiment analysis, multi-language support. Target: Shopify merchants with 100+ support tickets/month. Reduces resolution time by 80% through ML-based response suggestions...",
      },
      {
        source: "github",
        title: "velora-api/README.md",
        snippet: "Core backend for Velora AI customer support platform. Built with FastAPI, PostgreSQL, and pgvector for semantic search. Uses Gemini for embeddings and response generation. Key modules: RAG pipeline, ticket classifier, response generator...",
      },
      {
        source: "slack",
        title: "#product - Sarah Chen",
        snippet: "Just shipped v2.0 with the new AI auto-response feature! Early beta customers reporting 85% reduction in manual ticket handling. Next: multi-channel support (email, SMS, WhatsApp).",
      },
    ],
  },
  "Who are our main competitors?": {
    answer:
      "Our main competitors are Intercom (enterprise focus with $50k+ ACV), Zendesk (legacy platform with slow innovation), and Gorgias (e-commerce specialized but expensive). We position ourselves as a modern AI-native solution at 1/3 the price of Gorgias.",
    citations: [
      {
        source: "notion",
        title: "Competitive Analysis Q1 2024",
        snippet: "Main competitors: Intercom ($50k+ ACV, enterprise), Zendesk (legacy, slow AI adoption), Gorgias ($300/mo, e-commerce focus). Our positioning: AI-native, affordable ($99-299/mo), faster implementation. Win rate against Gorgias: 67%...",
      },
      {
        source: "slack",
        title: "#sales - Mike Rodriguez",
        snippet: "Lost deal to Gorgias today but they're paying 3x what we quoted. Customer cited 'brand recognition' but admitted our AI features are better. We need more case studies to compete on trust.",
      },
      {
        source: "github",
        title: "velora-dashboard/CHANGELOG.md",
        snippet: "v2.1.0 - Added competitive comparison widget showing Velora vs Gorgias/Intercom response times. Integrated benchmarking data from support ticket datasets...",
      },
    ],
  },
}

export const competitorIntel = [
  {
    competitor: "Intercom",
    type: "pricing",
    content: "Raised prices 15% in January 2024",
    timestamp: "2024-02-01",
  },
  {
    competitor: "Zendesk",
    type: "acquisition",
    content: "Acquired Ultimate.ai for $400M",
    timestamp: "2024-01-28",
  },
  {
    competitor: "Gorgias",
    type: "growth",
    content: "Hit 12,000 customers and $25M ARR",
    timestamp: "2024-02-03",
  },
]
