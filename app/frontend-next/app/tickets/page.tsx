"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TicketList } from "@/components/ticket/TicketList";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { Alert, Button } from "@/components/ui";
import { api } from "@/lib/api";
import { canCreateTickets } from "@/lib/auth";

export default function TicketsPage() {
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canCreateTicket = !authQuery.isError && canCreateTickets(authQuery.data);

  useEffect(() => {
    if (!canCreateTicket) setNewTicketOpen(false);
  }, [canCreateTicket]);

  return (
    <>
      {authQuery.isError && (
        <div className="mx-auto mb-6 w-full max-w-[1440px]">
          <Alert
            variant="warning"
            title="Ticket control access could not be verified"
            action={<Button size="sm" variant="secondary" onClick={() => void authQuery.refetch()} pending={authQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}
          >
            The synchronized queue remains available when its data source responds, but create and bulk controls stay hidden until your access is verified.
          </Alert>
        </div>
      )}
      <TicketList onCreate={canCreateTicket ? () => setNewTicketOpen(true) : undefined} />
      {canCreateTicket && <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />}
    </>
  );
}
