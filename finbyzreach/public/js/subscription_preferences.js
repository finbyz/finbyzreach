window.finbyzreachPreferences = {
    render(frm, email) {
        const field = frm.fields_dict.custom_email_preferences_html;
        if (!field || frm.is_new()) return;
        const $root = field.$wrapper.empty();
        frappe.call({
            method: "finbyzreach.subscription_preferences.get_person_preferences",
            args: { doctype: frm.doctype, name: frm.doc.name, email: email || "" },
            callback({ message }) {
                if (!message) return;
                const topics = message.topics || [];
                const appendStatus = ($target, topic) => {
                    const unknown = topic.status === "Unknown";
                    const $status = $("<span>")
                        .addClass("fr-subscriptions-status fr-subscriptions-status--" + String(topic.status).toLowerCase())
                        .text(unknown ? __("No opt-in") : __(topic.status))
                        .appendTo($target);
                    if (unknown) $status.attr("title", __("No subscription choice has been recorded for this email."));
                };
                const $panel = $("<section class='fr-subscriptions'>").appendTo($root);
                const $heading = $("<button type='button' class='fr-subscriptions-head' aria-expanded='false'>").appendTo($panel);
                const $headingCopy = $("<span>").appendTo($heading);
                $("<strong>").text(__("Communication subscriptions")).appendTo($headingCopy);
                $("<small>").text(message.email || __("No email address")).appendTo($headingCopy);
                $("<span class='fr-subscriptions-chevron' aria-hidden='true'>").text("⌄").appendTo($heading);

                const $summary = $("<div class='fr-subscriptions-summary'>").appendTo($panel);
                const mailingTypes = topics.filter(topic => topic.category === "Mailing Type");
                const preferred = ["Marketing E-Mails", "Stammtisch Newsletter", "Pressemitteilungen"];
                const summaryTopics = preferred.map(name => mailingTypes.find(topic => topic.name === name)).filter(Boolean);
                if (!summaryTopics.length) summaryTopics.push(...mailingTypes.slice(0, 3));
                summaryTopics.forEach(topic => {
                    const $item = $("<div class='fr-subscriptions-summary-item'>").appendTo($summary);
                    $("<span class='fr-subscriptions-summary-label'>").text(topic.label).appendTo($item);
                    appendStatus($item, topic);
                });
                $("<button type='button' class='fr-subscriptions-manage'>")
                    .text(__("Change communication subscriptions") + " ›")
                    .on("click", () => setOpen(true))
                    .appendTo($summary);

                const $body = $("<div class='fr-subscriptions-body'>").appendTo($panel);
                if (!message.email) {
                    $("<p>").text(__("Add an email address to manage subscriptions.")).appendTo($body);
                } else {
                    const $email = $("<div class='fr-subscriptions-email'>").appendTo($body);
                    if ((message.emails || []).length > 1) {
                        const $select = $("<select class='form-control input-sm'>").appendTo($email);
                        message.emails.forEach(address => $("<option>").val(address).text(address).appendTo($select));
                        $select.val(message.email).on("change", () => window.finbyzreachPreferences.render(frm, $select.val()));
                    } else {
                        $email.text(message.email);
                    }
                    const canEdit = (frappe.user_roles || []).some(role => ["Marketing Manager", "System Manager"].includes(role));
                    [["Mailing Type", __("Email types")], ["Topic", __("Topics")]].forEach(([category, title]) => {
                        const groupTopics = topics.filter(topic => topic.category === category);
                        if (!groupTopics.length) return;
                        const $group = $("<section class='fr-subscriptions-group'>").appendTo($body);
                        $("<h5>").text(title).appendTo($group);
                        const $list = $("<div class='fr-subscriptions-list'>").appendTo($group);
                        groupTopics.forEach(topic => {
                            const $row = $("<div class='fr-subscriptions-row'>").appendTo($list);
                            const $copy = $("<div class='fr-subscriptions-copy'>").appendTo($row);
                            $("<strong>").text(topic.label).appendTo($copy);
                            if (topic.description) $("<small>").text(topic.description).appendTo($copy);
                            appendStatus($row, topic);
                            if (!canEdit) return;
                            const subscribed = topic.status === "Subscribed";
                            const $button = $("<button type='button' class='btn btn-xs btn-default'>")
                                .text(subscribed ? __("Unsubscribe") : __("Subscribe")).appendTo($row);
                            $button.on("click", () => {
                                $button.prop("disabled", true);
                                frappe.call({
                                    method: "finbyzreach.subscription_preferences.set_person_preference",
                                    args: {doctype: frm.doctype, name: frm.doc.name, email: message.email, topic: topic.name, subscribed: subscribed ? 0 : 1},
                                    callback({message: status}) {
                                        if (status === "Pending") frappe.msgprint(__("Confirmation pending. Please check the inbox."));
                                        window.finbyzreachPreferences.render(frm, message.email);
                                    },
                                    error() { $button.prop("disabled", false); }
                                });
                            });
                        });
                    });
                }
                const setOpen = open => {
                    frm.__finbyzSubscriptionOpen = open;
                    $panel.toggleClass("is-open", open);
                    $heading.attr("aria-expanded", open ? "true" : "false");
                    $summary.toggle(!open);
                    $body.toggle(open);
                };
                $heading.on("click", () => setOpen(!frm.__finbyzSubscriptionOpen));
                setOpen(Boolean(frm.__finbyzSubscriptionOpen));
            }
        });
    }
};
