export class ModelSelector {
    constructor(selectElement) {
        this.selectElement = selectElement;
    }

    render(models, selectedModelKey) {
        if (!this.selectElement) {
            return;
        }

        const options = [];
        for (const model of models) {
            const option = document.createElement("option");
            option.value = model.key || model.name;
            option.textContent = model.name;
            option.selected = option.value === selectedModelKey;
            option.title = model.description || model.name;
            options.push(option);
        }

        this.selectElement.replaceChildren(...options);
    }

    setDisabled(isDisabled) {
        if (!this.selectElement) {
            return;
        }
        this.selectElement.disabled = isDisabled;
    }
}
