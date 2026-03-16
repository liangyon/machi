/**
 * Dialog for writing a reaction/review on a watchlist item.
 */

"use client";

import { useState } from "react";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

interface ReactionDialogProps {
  currentReaction: string | null;
  onSave: (reaction: string) => void;
}

export function ReactionDialog({ currentReaction, onSave }: ReactionDialogProps) {
  const [text, setText] = useState(currentReaction || "");
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
            title="Write a reaction"
          />
        }
      >
        <MessageSquare className="h-3.5 w-3.5" />
        <span className="sr-only">Reaction</span>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Your Reaction</DialogTitle>
          <DialogDescription>
            Write your thoughts after watching. This is just for you.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={text}
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
            setText(e.target.value)
          }
          placeholder="What did you think? Any standout moments?"
          rows={4}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              onSave(text);
              setOpen(false);
            }}
          >
            Save Reaction
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
