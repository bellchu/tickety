"use client";

import { useState } from "react";
import { TicketList } from "@/components/ticket/TicketList";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";

export default function TicketsPage() {
  const [newTicketOpen, setNewTicketOpen] = useState(false);

  return (
    <>
      <TicketList onCreate={() => setNewTicketOpen(true)} />
      <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />
    </>
  );
}
