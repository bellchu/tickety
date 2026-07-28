"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TicketList } from "@/components/ticket/TicketList";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { api } from "@/lib/api";
import { canCreateTickets } from "@/lib/auth";

export default function TicketsPage() {
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canCreateTicket = canCreateTickets(authQuery.data);

  return (
    <>
      <TicketList onCreate={canCreateTicket ? () => setNewTicketOpen(true) : undefined} />
      {canCreateTicket && <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />}
    </>
  );
}
