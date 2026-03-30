import { permanentRedirect } from "next/navigation";

export default function ImportPage() {
  permanentRedirect("/profile?tab=import");
}
