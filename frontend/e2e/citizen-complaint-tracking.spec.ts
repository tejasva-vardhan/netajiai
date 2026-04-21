import { expect, test } from "@playwright/test";

test("citizen can file complaint and track by ID", async ({ context, page }) => {
  const mockComplaintId = "NETA-TEST-12345678";

  await context.grantPermissions(["geolocation"], {
    origin: "http://127.0.0.1:3000",
  });
  await context.setGeolocation({
    latitude: 23.2599,
    longitude: 77.4126,
  });

  await page.route("**/chat", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "complaint_registered",
        field: "done",
        reply: `✅ Your complaint has been registered!\nComplaint ID: ${mockComplaintId}\nDepartment: Public Works Department (PWD)`,
      }),
    });
  });

  await page.route(`**/api/track/${mockComplaintId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        complaint_id: mockComplaintId,
        status: "pending",
        issue_type: "road",
        created_at: new Date().toISOString(),
        department: "Public Works Department (PWD)",
        escalation_level: 1,
        current_level_label: "L1 Officer (Local Officer — e.g., JE)",
        escalation_matrix: {
          L1: {
            role: "L1 Officer (Local Officer — e.g., JE)",
            email: "je.road.bhopal@mp.gov.in",
          },
          L2: {
            role: "L2 Officer (Zonal Officer — e.g., AE / Commissioner)",
            email: "commissioner.bhopal@mp.gov.in",
          },
          L3: {
            role: "L3 Officer (State Head — e.g., Department Secretary)",
            email: "secy.road.mp@gov.in",
          },
        },
      }),
    });
  });

  // 1) Open homepage.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Aapka Digital Janpratinidhi/i })).toBeVisible();

  // 2) Click "File a New Complaint".
  await page.getByRole("link", { name: /File a New Complaint/i }).click();
  await expect(page).toHaveURL(/\/chat$/);

  // 3) Geolocation is mocked above. Wait until chat input is ready.
  const chatInput = page.getByPlaceholder("अपनी शिकायत लिखें...");
  await expect(chatInput).toBeVisible({ timeout: 30000 });

  // 4) Type a dummy complaint and send.
  await chatInput.fill("Road is damaged near central bus stand.");
  await page.getByRole("button", { name: "Send" }).click();

  // 5) Capture resulting Complaint ID from chat text.
  const complaintLine = page.getByText(new RegExp(`Complaint ID:\\s*${mockComplaintId}`));
  await expect(complaintLine).toBeVisible();
  const complaintText = (await complaintLine.textContent()) ?? "";
  const matched = complaintText.match(/Complaint ID:\s*([A-Z0-9-]+)/i);
  const capturedComplaintId = matched?.[1];
  expect(capturedComplaintId).toBe(mockComplaintId);

  // 6) Go to tracking page and verify this ID exists.
  await page.goto("/track");
  await page.getByLabel("Complaint ID").fill(capturedComplaintId ?? "");
  await page.getByRole("button", { name: "Track" }).click();

  await expect(page.getByText(mockComplaintId)).toBeVisible();
  await expect(page.getByText(/Status/i)).toBeVisible();
  await expect(page.getByText(/Pending/i)).toBeVisible();
});
