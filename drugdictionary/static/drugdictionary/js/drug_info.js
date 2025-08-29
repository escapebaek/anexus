document.addEventListener("DOMContentLoaded", function () {
    const sectionButtons = document.querySelectorAll(".section-btn");

    sectionButtons.forEach((button) => {
      button.addEventListener("click", function () {
        const clickedCard = this.closest(".drug-card");
        const contentArea = clickedCard.querySelector(".section-content-area");
        const sectionTitle = contentArea.querySelector(".section-title");
        const sectionContent = contentArea.querySelector(".section-content");
        const section = this.getAttribute("data-section");
        const drugId = this.getAttribute("data-drug-id");

        // Check if this card is already expanded
        const isExpanded = clickedCard.classList.contains("expanded-card");

        // Reset all cards first
        document.querySelectorAll(".drug-card").forEach((card) => {
          card.classList.remove("expanded-card");
          const otherContent = card.querySelector(".section-content-area");
          if (otherContent) {
            otherContent.classList.remove("expanded");
            otherContent.classList.add("d-none");
          }
          card
            .querySelectorAll(".section-btn")
            .forEach((btn) => btn.classList.remove("active"));
        });

        // If the card wasn't expanded before or a different section was clicked, expand it
        if (!isExpanded || this.classList.contains("active") === false) {
          // Expand the clicked card
          clickedCard.classList.add("expanded-card");
          this.classList.add("active");
          contentArea.classList.remove("d-none");

          // Use setTimeout to ensure the display change happens before adding the expanded class
          setTimeout(() => {
            contentArea.classList.add("expanded");
          }, 10);

          // 섹션 아이콘 & 제목
          let iconClass = "fas fa-info-circle";
          if (section === "indications") iconClass = "fas fa-check-circle";
          else if (section === "dosage") iconClass = "fas fa-prescription";
          else if (section === "warnings")
            iconClass = "fas fa-exclamation-triangle";
          else if (section === "adverse_reactions")
            iconClass = "fas fa-allergies";
          else if (section === "contraindications") iconClass = "fas fa-ban";
          sectionTitle.innerHTML = `<i class="${iconClass} me-2"></i>${this.textContent.trim()}`;

          // 로딩 스피너
          sectionContent.innerHTML = `
            <div class="spinner-border text-primary" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
          `;

          // Smooth scroll to the expanded card
          setTimeout(() => {
            clickedCard.scrollIntoView({
              behavior: "smooth",
              block: "start",
            });
          }, 100);

          // Adjust grid layout for expanded card
          const drugList = document.querySelector(".drug-list");
          drugList.style.display = "block"; // Temporarily disable grid layout
          setTimeout(() => {
            drugList.style.display = ""; // Re-enable grid layout after expansion
          }, 500);

          // AJAX
          fetch(
            `/drugdictionary/get-section/?drug_id=${drugId}&section=${section}`
          )
            .then((response) => response.json())
            .then((data) => {
              if (data.content) {
                let contentHtml = "";
                data.content.forEach((item) => {
                  contentHtml += `<p>${item}</p>`;
                });
                sectionContent.innerHTML = contentHtml;
              } else if (data.error) {
                sectionContent.innerHTML = `<div class="alert alert-danger">${data.error}</div>`;
              } else {
                sectionContent.innerHTML = "<p>No information available</p>";
              }
            })
            .catch((error) => {
              console.error("Error:", error);
              sectionContent.innerHTML =
                '<div class="alert alert-danger">Error loading content. Please try again.</div>';
            });
        }
      });
    });
  });
