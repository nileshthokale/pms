import { neon } from "@neon/ai-sdk-provider";
import { generateText } from "ai";

async function main() {
  console.log("Attempting model call through Neon AI Gateway via @neon/ai-sdk-provider...");
  try {
    const { text } = await generateText({
      model: neon("gpt-5-mini"),
      prompt: "Respond with the single word: Connected",
    });
    console.log("Model response:", text);
  } catch (err) {
    console.log("Error status:", err.status || err.statusCode || err.name);
    console.log("Error message:", err.message);
    if (err.data) {
      console.log("Error details:", JSON.stringify(err.data, null, 2));
    }
  }
}

main();
