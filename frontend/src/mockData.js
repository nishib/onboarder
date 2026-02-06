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
        snippet: "AI-powered customer support for e-commerce...",
      },
      {
        source: "github",
        title: "velora-api README",
        snippet: "Core backend for Velora AI customer support platform...",
      },
    ],
  },
  "Who are our main competitors?": {
    answer:
      "Our main competitors are Intercom (enterprise focus with $50k+ ACV), Zendesk (legacy platform with slow innovation), and Gorgias (e-commerce specialized but expensive). We position ourselves as a modern AI-native solution at 1/3 the price of Gorgias.",
    citations: [
      {
        source: "notion",
        title: "Competitive Landscape Analysis",
        snippet: "Main competitors: Intercom, Zendesk, Gorgias...",
      },
      {
        source: "slack",
        title: "#general - Lisa Wang",
        snippet: "How is this different from Gorgias?...",
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
