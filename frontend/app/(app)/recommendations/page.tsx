import { permanentRedirect } from "next/navigation";

export default function RecommendationsPage() {
  permanentRedirect("/discover?tab=history");
}
